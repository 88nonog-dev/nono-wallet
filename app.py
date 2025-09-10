# ------------------------------------------------------------
# Project: nono-wallet
# Author: Mohammed Nasser Zimam (محمد ناصر زمام)
# Company: شركة الصقر الملكي للمقاولات العامة
# Year: 2025
# ------------------------------------------------------------

import os
import uuid
import io
import csv
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, Response, abort
from sqlalchemy import create_engine, text

# ------------------------------------------------------------------------------
# Flask app
# ------------------------------------------------------------------------------
app = Flask(__name__)
application = app  # alias لو احتجنا wsgi:application

# ------------------------------------------------------------------------------
# Database (Neon Postgres مع fallback SQLite) + إنشاء/ترقية سكيمة
# ------------------------------------------------------------------------------
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()

def _build_engine():
    url = DATABASE_URL
    if not url:
        # fallback محلي لكي لا يطيح السيرفر لو ماكو DATABASE_URL
        return create_engine("sqlite:///nono_wallet.sqlite3", pool_pre_ping=True)
    # إجبار SSL مع Neon/Postgres
    if url.startswith("postgres") and "sslmode" not in url:
        url = url + ("&" if "?" in url else "?") + "sslmode=require"
    return create_engine(url, pool_pre_ping=True)

engine = _build_engine()

def ensure_schema():
    """
    تضمن وجود الجداول الأساسية، وترقية جدول wallets لإضافة العمود name إذا كان مفقود،
    وترقية جدول transactions لإضافة عمود idempotency key + إنشاء الفهارس المفيدة.
    """
    with engine.begin() as conn:
        # جداول أساسية
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS wallets (
            id TEXT PRIMARY KEY,
            balance NUMERIC NOT NULL DEFAULT 0
        )"""))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            wallet_id TEXT NOT NULL,
            type TEXT NOT NULL,            -- deposit | withdraw
            amount NUMERIC NOT NULL,
            created_at TIMESTAMP NOT NULL,
            FOREIGN KEY(wallet_id) REFERENCES wallets(id)
        )"""))

        # --- ترقية: wallets.name ---
        try:
            exists = conn.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name='wallets' AND column_name='name'
            """)).scalar()
            if not exists:
                conn.execute(text("ALTER TABLE wallets ADD COLUMN name TEXT UNIQUE"))
        except Exception:
            # SQLite fallback
            try:
                rows = conn.execute(text("PRAGMA table_info(wallets)")).mappings().all()
                has_name = any(r.get("name") == "name" for r in rows)
                if not has_name:
                    conn.execute(text("ALTER TABLE wallets ADD COLUMN name TEXT UNIQUE"))
            except Exception as e:
                print("SCHEMA wallets.name WARNING:", e)

        # --- ترقية: transactions.idem_key (idempotency) ---
        try:
            exists = conn.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name='transactions' AND column_name='idem_key'
            """)).scalar()
            if not exists:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN idem_key TEXT"))
                # unique index
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_idem ON transactions(idem_key)"))
        except Exception:
            # SQLite fallback
            try:
                rows = conn.execute(text("PRAGMA table_info(transactions)")).mappings().all()
                has_col = any(r.get("name") == "idem_key" for r in rows)
                if not has_col:
                    conn.execute(text("ALTER TABLE transactions ADD COLUMN idem_key TEXT"))
                # create unique index (SQLite يسمح IF NOT EXISTS)
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_idem ON transactions(idem_key)"))
            except Exception as e:
                print("SCHEMA transactions.idem_key WARNING:", e)

        # --- فهارس مفيدة ---
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_wallets_name ON wallets(name)"))
        except Exception:
            pass
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tx_wallet_created ON transactions(wallet_id, created_at DESC)"))
        except Exception:
            pass

try:
    ensure_schema()
except Exception as e:
    print("SCHEMA INIT/UPGRADE WARNING:", e)

# ------------------------------------------------------------------------------
# Security: API Token (X-Api-Key) + WHOAMI_TOKEN
# ------------------------------------------------------------------------------
API_TOKEN = (os.environ.get("API_TOKEN") or "").strip()
WHOAMI_TOKEN = (os.environ.get("WHOAMI_TOKEN") or "").strip()

def require_api_key(fn):
    @wraps(fn)
    def _wrap(*a, **kw):
        token = request.headers.get("X-Api-Key", "")
        if not API_TOKEN or token != API_TOKEN:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return fn(*a, **kw)
    return _wrap

# ------------------------------------------------------------------------------
# Rate limit بسيط داخل الذاكرة (يفضَّل WEB_CONCURRENCY=1 لإظهاره بوضوح)
# ------------------------------------------------------------------------------
_rate_state = {}  # key -> {count, reset_at}
def rate_limit(limit:int, window_sec:int=60, key_func=None):
    def deco(fn):
        @wraps(fn)
        def _wrap(*a, **kw):
            k = "global"
            if key_func:
                try:
                    k = key_func()
                except Exception:
                    k = "global"
            now = time.time()
            st = _rate_state.get(k)
            if not st or now >= st["reset_at"]:
                st = {"count": 0, "reset_at": now + window_sec}
                _rate_state[k] = st
            if st["count"] >= limit:
                return jsonify({"ok": False, "error": "Too Many Requests"}), 429
            st["count"] += 1
            return fn(*a, **kw)
        return _wrap
    return deco

def _rate_key(prefix:str):
    def _k():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "0")
        tk = request.headers.get("X-Api-Key", "")
        return f"{prefix}|{ip}|{tk}"
    return _k

# ------------------------------------------------------------------------------
# Health & Basic
# ------------------------------------------------------------------------------
@app.get("/__ping")
def __ping():
    routes = [r.rule for r in app.url_map.iter_rules() if r.endpoint != 'static']
    return jsonify({"ok": True, "routes_count": len(routes), "routes": routes})

@app.get("/health")
def health():
    return jsonify({"ok": True, "name": "nono-wallet", "time": datetime.utcnow().isoformat() + "Z"})

@app.get("/whoami")
def whoami():
    required = (WHOAMI_TOKEN or "").strip()
    sent = (request.headers.get("X-Auth-Token") or "").strip()
    if not required:
        return jsonify({"ok": False, "error": "WHOAMI_TOKEN not configured"}), 500
    if sent != required:
        abort(401)
    return jsonify({"ok": True, "user": "nono-wallet", "env": os.getenv("RAILWAY_ENVIRONMENT_NAME", "production")})

@app.get("/")
def home():
    return jsonify({"ok": True, "name": "nono-wallet", "time": datetime.utcnow().isoformat() + "Z"})

# ------------------------------------------------------------------------------
# Wallet APIs
# ------------------------------------------------------------------------------

@app.post("/wallet/create")
@require_api_key
def wallet_create():
    data = request.get_json(silent=True) or {}
    name = data.get("name") or f"wallet-{uuid.uuid4().hex[:6]}"
    wallet_id = str(uuid.uuid4())

    # إنشاء محفظة بدون الاعتماد على عمود name (للتوافق الخلفي)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO wallets (id, balance) VALUES (:id, 0)"),
                     {"id": wallet_id})
        # تسجيل معاملة أولية deposit=0 (بدل create)
        conn.execute(text("""INSERT INTO transactions
                (id, wallet_id, type, amount, created_at)
                VALUES (:id,:wid,:typ,:amt,:ts)"""),
                {"id": str(uuid.uuid4()), "wid": wallet_id, "typ": "deposit",
                 "amt": 0, "ts": datetime.utcnow()})

    # محاولة تعيين الاسم إن كان العمود موجود
    try:
        with engine.begin() as conn2:
            conn2.execute(text("UPDATE wallets SET name = :name WHERE id = :id"),
                          {"id": wallet_id, "name": name})
    except Exception as e:
        print("NAME UPDATE SKIPPED:", e)

    return jsonify({"ok": True, "wallet": {"id": wallet_id, "name": name, "balance": 0}})

def _idempotent_exists(idem_key:str):
    if not idem_key:
        return None
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT id, wallet_id, type, amount, created_at
            FROM transactions WHERE idem_key=:k
        """), {"k": idem_key}).mappings().first()
        return dict(row) if row else None

@app.post("/wallet/deposit")
@require_api_key
@rate_limit(limit=20, window_sec=60, key_func=_rate_key("deposit"))
def wallet_deposit():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id")
    amount = float(data.get("amount") or 0)
    idem = request.headers.get("Idempotency-Key", "").strip()
    if idem:
        ex = _idempotent_exists(idem)
        if ex:
            # إعادة نفس الاستجابة ولكن لا نعيد تطبيق العملية
            with engine.begin() as conn:
                bal = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"),
                                   {"id": ex["wallet_id"]}).scalar()
            return jsonify({"ok": True, "idempotent": True,
                            "tx": ex, "wallet": {"id": ex["wallet_id"],
                                                 "balance": float(bal or 0)}})
    if not wallet_id or amount <= 0:
        return jsonify({"ok": False, "error": "wallet_id and positive amount required"}), 400

    with engine.begin() as conn:
        conn.execute(text("UPDATE wallets SET balance = balance + :amt WHERE id=:id"),
                     {"amt": amount, "id": wallet_id})
        conn.execute(text("""INSERT INTO transactions
            (id, wallet_id, type, amount, created_at, idem_key)
            VALUES (:id,:wid,:typ,:amt,:ts,:idem)"""),
            {"id": str(uuid.uuid4()), "wid": wallet_id, "typ": "deposit",
             "amt": amount, "ts": datetime.utcnow(), "idem": idem or None})
        bal = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"),
                           {"id": wallet_id}).scalar()
    return jsonify({"ok": True, "wallet": {"id": wallet_id, "balance": float(bal or 0)}})

@app.post("/wallet/withdraw")
@require_api_key
@rate_limit(limit=15, window_sec=60, key_func=_rate_key("withdraw"))
def wallet_withdraw():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id")
    amount = float(data.get("amount") or 0)
    idem = request.headers.get("Idempotency-Key", "").strip()
    if idem:
        ex = _idempotent_exists(idem)
        if ex:
            with engine.begin() as conn:
                bal = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"),
                                   {"id": ex["wallet_id"]}).scalar()
            return jsonify({"ok": True, "idempotent": True,
                            "tx": ex, "wallet": {"id": ex["wallet_id"],
                                                 "balance": float(bal or 0)}})
    if not wallet_id or amount <= 0:
        return jsonify({"ok": False, "error": "wallet_id and positive amount required"}), 400

    with engine.begin() as conn:
        bal = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"),
                           {"id": wallet_id}).scalar()
        if bal is None or float(bal) < amount:
            return jsonify({"ok": False, "error": "insufficient funds"}), 400
        conn.execute(text("UPDATE wallets SET balance = balance - :amt WHERE id=:id"),
                     {"amt": amount, "id": wallet_id})
        conn.execute(text("""INSERT INTO transactions
            (id, wallet_id, type, amount, created_at, idem_key)
            VALUES (:id,:wid,:typ,:amt,:ts,:idem)"""),
            {"id": str(uuid.uuid4()), "wid": wallet_id, "typ": "withdraw",
             "amt": amount, "ts": datetime.utcnow(), "idem": idem or None})
        bal2 = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"),
                            {"id": wallet_id}).scalar()
    return jsonify({"ok": True, "wallet": {"id": wallet_id, "balance": float(bal2 or 0)}})

@app.get("/wallet/balance")
@require_api_key
def wallet_balance():
    wallet_id = request.args.get("wallet_id")
    if not wallet_id:
        return jsonify({"ok": False, "error": "wallet_id required"}), 400
    with engine.begin() as conn:
        bal = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"),
                           {"id": wallet_id}).scalar()
    return jsonify({"ok": True, "wallet": {"id": wallet_id, "balance": float(bal or 0)}})

# ------------------------------------------------------------------------------
# Transactions list + CSV (مع فلاتر)
# ------------------------------------------------------------------------------
@app.get("/transactions")
@require_api_key
def transactions_list():
    wallet_id = request.args.get("wallet_id")
    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")

    where = ["1=1"]; args = {}
    if wallet_id:
        where.append("wallet_id = :wid"); args["wid"] = wallet_id
    if date_from:
        where.append("created_at >= :df"); args["df"] = date_from
    if date_to:
        where.append("created_at <= :dt"); args["dt"] = date_to

    sql = f"""SELECT id, wallet_id, type, amount, created_at
              FROM transactions
              WHERE {' AND '.join(where)}
              ORDER BY created_at DESC
              LIMIT 500"""
    with engine.begin() as conn:
        rows = conn.execute(text(sql), args).mappings().all()
    return jsonify({"ok": True, "items": [dict(r) for r in rows]})

@app.get("/transactions/export.csv")
@require_api_key
def transactions_export():
    wallet_id = request.args.get("wallet_id")
    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")

    # دعم فاصل الأعمدة واسم الملف
    sep = request.args.get("sep", ",")
    if sep not in {",", ";", "|", "\t"}:
        sep = ","
    filename = request.args.get("filename", "transactions.csv")

    where = ["1=1"]; args = {}
    if wallet_id:
        where.append("wallet_id = :wid"); args["wid"] = wallet_id
    if date_from:
        where.append("created_at >= :df"); args["df"] = date_from
    if date_to:
        where.append("created_at <= :dt"); args["dt"] = date_to

    sql = f"""SELECT id, wallet_id, type, amount, created_at
              FROM transactions
              WHERE {' AND '.join(where)}
              ORDER BY created_at DESC"""

    def generate():
        sio = io.StringIO()
        writer = csv.writer(sio, delimiter=sep, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)

        # العناوين
        writer.writerow(["id", "wallet_id", "type", "amount", "created_at"])
        yield sio.getvalue(); sio.seek(0); sio.truncate(0)

        with engine.begin() as conn:
            for r in conn.execute(text(sql), args):
                writer.writerow([
                    r.id,
                    r.wallet_id,
                    r.type,
                    str(r.amount),
                    getattr(r.created_at, "isoformat", lambda: str(r.created_at))()
                ])
                yield sio.getvalue(); sio.seek(0); sio.truncate(0)

    resp = Response(generate(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

# ------------------------------------------------------------------------------
# Dashboard (Purple Wide UI) — token مخفي
# ------------------------------------------------------------------------------
@app.get("/dashboard")
def dashboard():
    return DASHBOARD_HTML

DASHBOARD_HTML = """<!doctype html><html lang="en" dir="ltr"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Nono Wallet Dashboard</title>
<style>
  :root{
    --bg1:#6a11cb; --bg2:#2575fc;
    --card:#ffffff; --line:#e6e8ef; --text:#0f172a; --muted:#667085;
    --primary:#6a11cb; --primary2:#7b3efc; --ok:#16a34a; --warn:#f59e0b; --err:#ef4444;
  }
  *{box-sizing:border-box}
  body{margin:0;background:linear-gradient(135deg,var(--bg1),var(--bg2)) fixed;min-height:100vh;
       font-family:system-ui,Segoe UI,Arial,sans-serif;color:var(--text)}
  header{padding:22px 28px;color:#fff;display:flex;align-items:center;justify-content:space-between}
  header h1{margin:0;font-size:20px;font-weight:700}
  main{max-width:1200px;margin:0 auto;padding:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.12)}
  .hero{display:grid;grid-template-columns:1.4fr .8fr;gap:18px;padding:24px}
  .hero .balance{color:#fff;background:linear-gradient(135deg,rgba(255,255,255,.15),rgba(255,255,255,.05));
     border-radius:18px;padding:22px;border:1px solid rgba(255,255,255,.25);backdrop-filter:blur(4px)}
  .hero h2{margin:0 0 8px 0;color:#fff;opacity:.95;font-weight:600}
  .hero .val{font-size:42px;font-weight:800;letter-spacing:.5px;color:#fff;margin:6px 0 16px 0}
  .hero .actions{display:flex;gap:10px;flex-wrap:wrap}
  .btn{border:1px solid #cfd4dc;border-radius:12px;padding:10px 14px;background:#fff;cursor:pointer}
  .btn.primary{background:linear-gradient(135deg,var(--primary),var(--primary2));border:none;color:#fff}
  .btn.ghost{background:#fff;border-color:#d9dbe3;color:var(--primary)}
  .chip{border-radius:999px;background:#fff;border:1px solid #d9dbe3;padding:8px 12px}
  .panel{padding:16px 18px}
  .row{display:flex;gap:12px;flex-wrap:wrap}
  .row>*{flex:1;min-width:190px}
  input,select{width:100%;border:1px solid #cfd4dc;background:#fff;color:var(--text);border-radius:12px;padding:10px 12px}
  input[type=password]{font-family:Segoe UI, Arial, sans-serif}
  table{width:100%;border-collapse:collapse;background:#fff}
  th,td{padding:12px;border-bottom:1px solid #eef0f5;text-align:left}
  th{color:#334155;font-weight:600}
  .status{display:inline-flex;align-items:center;gap:8px}
  .dot{width:10px;height:10px;border-radius:50%}
  .ok{background:var(--ok)} .pen{background:var(--warn)} .bad{background:var(--err)}
  .pill{display:inline-block;padding:6px 10px;border-radius:999px;border:1px solid #e2e7f0;background:#f8fafc;font-size:12px}
  .footer{color:#e5e7eb;text-align:center;padding:22px 10px}
  .klabel{color:#e5e7eb;font-size:12px}
  .donut{width:180px;height:180px;background:
      radial-gradient(closest-side, #0000 74%, #0000 0),
      conic-gradient(#7c3aed var(--pct), #ddd 0);
      border-radius:50%;position:relative;border:1px solid rgba(255,255,255,.25)}
  .donut::after{content:attr(data-label);position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
      color:#fff;font-weight:700;font-size:18px}
  .grid{display:grid;grid-template-columns:1fr;gap:16px}
  @media(min-width:900px){ .grid{grid-template-columns:1fr 1fr} }
</style>
</head>
<body>
  <header>
    <h1>نونو-والِت • لوحة التحكم</h1>
    <div class="klabel">استخدم هيدر <b>X-Api-Key</b> (يحفظ محليًا)</div>
  </header>

  <main>
    <!-- HERO -->
    <section class="card hero" id="hero">
      <div class="balance">
        <h2>Current Balance</h2>
        <div class="val" id="curBal">$0.00</div>
        <div class="actions">
          <button class="btn primary" id="btnDeposit">+ Deposit</button>
          <button class="btn" id="btnWithdraw">Withdrawal</button>
          <span class="chip" id="chipOver500">&gt; 500</span>
        </div>
      </div>
      <div class="balance" style="display:flex;align-items:center;justify-content:center">
        <div id="donut" class="donut" style="--pct:0deg" data-label="0%"></div>
      </div>
    </section>

    <!-- FILTERS -->
    <section class="card panel">
      <div class="row">
        <input id="apiKey" type="password" placeholder="API Token" />
        <input id="walletId" placeholder="Wallet ID (uuid)" />
        <input id="dateFrom" type="date" />
        <input id="dateTo" type="date" />
        <input id="searchTxt" placeholder="Search (type, id...)" />
        <div style="display:flex;gap:10px;align-items:center;justify-content:flex-end">
          <button class="btn" id="btnSaveKey">Save</button>
          <a class="btn ghost" id="btnCsv" href="#">Export CSV</a>
          <button class="btn primary" id="btnNewTx">+ New Transaction</button>
        </div>
      </div>
    </section>

    <!-- TABLE -->
    <section class="card panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <h3 style="margin:0">Transactions</h3>
        <span class="pill" id="countLbl">0 items</span>
      </div>
      <div style="overflow:auto">
        <table id="tbl">
          <thead><tr><th>Date</th><th>Type</th><th>Amount</th><th>Status</th><th>ID</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </section>

    <!-- NEW TX PANEL -->
    <section class="card panel" id="newTx" style="display:none">
      <div class="row">
        <select id="txType">
          <option value="deposit">Deposit</option>
          <option value="withdraw">Withdrawal</option>
        </select>
        <input id="txAmount" type="number" min="0" step="0.00000001" placeholder="Amount" />
        <button class="btn primary" id="txDo">Submit</button>
        <button class="btn" id="txCancel">Cancel</button>
      </div>
      <div id="txMsg" style="margin-top:10px;color:var(--muted)"></div>
    </section>

    <div class="footer">© nono-wallet</div>
  </main>

<script>
const $ = s=>document.querySelector(s);
const tbody = $("#tbl tbody");
const apiKeyEl = $("#apiKey");
const walletEl = $("#walletId");
const fromEl = $("#dateFrom");
const toEl = $("#dateTo");
const searchEl = $("#searchTxt");
const donut = $("#donut");
const curBal = $("#curBal");
const btnCsv = $("#btnCsv");

const LS_KEY="nono_api_key", LS_WAL="nono_last_wallet";
apiKeyEl.value = localStorage.getItem(LS_KEY)||"";
walletEl.value = localStorage.getItem(LS_WAL)||"";

function hdr(){ return {"X-Api-Key": apiKeyEl.value.trim() }; }
function fmtMoney(n){ return new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:8}).format(Number(n)||0); }
function setDonut(pct){
  const deg = Math.max(0,Math.min(100,pct))*3.6;
  donut.style.setProperty("--pct", deg+"deg");
  donut.setAttribute("data-label", Math.round(pct)+"%");
}

$("#btnSaveKey").onclick = ()=>{
  localStorage.setItem(LS_KEY, apiKeyEl.value.trim());
  localStorage.setItem(LS_WAL, walletEl.value.trim());
  alert("Saved ✓");
};

$("#btnNewTx").onclick = ()=>$("#newTx").style.display="block";
$("#txCancel").onclick = ()=>$("#newTx").style.display="none";

async function fetchBalance(){
  const id = walletEl.value.trim();
  if(!id) return;
  try{
    const r = await fetch(`/wallet/balance?wallet_id=${encodeURIComponent(id)}`, {headers: hdr()});
    const j = await r.json();
    if(j.ok){
      curBal.textContent = fmtMoney(j.wallet.balance||0);
      const pct = Math.min(100, (Number(j.wallet.balance)||0) / 1000 * 100);
      setDonut(pct);
    }
  }catch(e){}
}

async function depositWithdraw(kind, amount){
  const id = walletEl.value.trim();
  if(!id) return alert("Wallet ID required");
  if(!(amount>0)) return alert("Amount must be > 0");
  const url = (kind==="deposit")?"/wallet/deposit":"/wallet/withdraw";
  const r = await fetch(url,{method:"POST",headers:{...hdr(),"Content-Type":"application/json"},
      body: JSON.stringify({wallet_id:id, amount:Number(amount)})});
  const j = await r.json();
  if(!j.ok) alert(j.error||"Error"); else { await fetchBalance(); await loadTx(); }
}

$("#btnDeposit").onclick = ()=>{ $("#newTx").style.display="block"; $("#txType").value="deposit"; }
$("#btnWithdraw").onclick = ()=>{ $("#newTx").style.display="block"; $("#txType").value="withdraw"; }
$("#txDo").onclick = async ()=>{
  const t = $("#txType").value, amt = Number($("#txAmount").value||0);
  $("#txMsg").textContent = "Processing...";
  await depositWithdraw(t, amt);
  $("#txMsg").textContent = "Done";
};

$("#chipOver500").onclick = ()=>{ searchEl.value=">500"; loadTx(); };

function matchSearch(it){
  const q = (searchEl.value||"").trim();
  if(!q) return true;
  if(q.startsWith(">")){
    const n = Number(q.slice(1));
    return (Number(it.amount)||0) > n;
  }
  const s = q.toLowerCase();
  return (it.id+it.type+it.wallet_id).toLowerCase().includes(s);
}

async function loadTx(){
  const qs = new URLSearchParams();
  const w = walletEl.value.trim();
  if(w) qs.set("wallet_id", w);
  const f = fromEl.value ? new Date(fromEl.value).toISOString() : "";
  const t = toEl.value   ? new Date(toEl.value).toISOString()   : "";
  if(f) qs.set("date_from", f);
  if(t) qs.set("date_to", t);

  try{
    const r = await fetch(`/transactions?${qs.toString()}`, {headers: hdr()});
    const j = await r.json();
    tbody.innerHTML = "";
    let cnt=0, dep=0, wd=0;
    if(j.ok){
      const items = (j.items||[]).filter(matchSearch);
      for(const it of items){
        cnt++;
        if(it.type==="deposit") dep+=Number(it.amount)||0;
        if(it.type==="withdraw") wd+=Number(it.amount)||0;

        const tr = document.createElement("tr");
        const status = (it.type==="withdraw"||it.type==="deposit") ? "Completed" : "Pending";
        const cls = status==="Completed" ? "ok" : "pen";
        tr.innerHTML = `
          <td>${new Date(it.created_at).toLocaleString()}</td>
          <td style="color:${it.type==='withdraw'?'#b42318':'#0f766e'}">${it.type}</td>
          <td>${fmtMoney(it.amount)}</td>
          <td><span class="status"><span class="dot ${cls}"></span>${status}</span></td>
          <td style="color:#64748b">${it.id}</td>`;
        tbody.appendChild(tr);
      }
      $("#countLbl").textContent = cnt+" items";
      const total = dep + wd;
      setDonut(total? (dep/total*100) : 0);
    }
    // CSV: نمرر sep و filename مناسبين لإكسل
    const fname = `transactions_${(w||'all').slice(0,8)}.csv`;
    btnCsv.href = `/transactions/export.csv?${qs.toString()}&sep=%3B&filename=${encodeURIComponent(fname)}`;
  }catch(e){}
}

apiKeyEl.addEventListener("change", ()=>localStorage.setItem(LS_KEY, apiKeyEl.value.trim()));
walletEl.addEventListener("change", ()=>{ localStorage.setItem(LS_WAL, walletEl.value.trim()); fetchBalance(); loadTx(); });
searchEl.addEventListener("input", ()=>loadTx());
fromEl.addEventListener("change", ()=>loadTx());
toEl.addEventListener("change", ()=>loadTx());

fetchBalance(); loadTx();
</script>
</body></html>"""
