# app.py
import os
import uuid
import json
import io
import csv
from datetime import datetime
from decimal import Decimal

from flask import Flask, request, jsonify, send_file, render_template_string

from sqlalchemy import (
    create_engine, Column, String, DateTime, Numeric, ForeignKey, Text, select, func
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session
from sqlalchemy.exc import IntegrityError, OperationalError

import requests

# ------------------------------------------------------------------------------
# Config
# ------------------------------------------------------------------------------
API_TOKEN = os.getenv("API_TOKEN", "")
WHOAMI_TOKEN = os.getenv("WHOAMI_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

NONO_LLM_URL = os.getenv("NONO_LLM_URL", "https://api.openai.com/v1/chat/completions")
NONO_LLM_KEY = os.getenv("NONO_LLM_KEY", "")
NONO_LLM_MODEL = os.getenv("NONO_LLM_MODEL", "gpt-4o-mini")

app = Flask(__name__)

# ------------------------------------------------------------------------------
# Database (SQLAlchemy, Neon Postgres)
# ------------------------------------------------------------------------------
if not DATABASE_URL:
    # Allow local dev with SQLite fallback (not used on Railway/Neon)
    DATABASE_URL = "sqlite:///nono_wallet.sqlite3"

connect_args = {}
if DATABASE_URL.startswith("postgres"):
    # Neon usually requires SSL
    connect_args = {"sslmode": "require"}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args if DATABASE_URL.startswith("postgres") else {},
)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()


def now_utc():
    return datetime.utcnow()


class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    balance = Column(Numeric(18, 8), nullable=False, default=Decimal("0"))
    created_at = Column(DateTime, default=now_utc, nullable=False)

    txns = relationship("Transaction", back_populates="wallet", cascade="all,delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    wallet_id = Column(String, ForeignKey("wallets.id"), index=True, nullable=False)
    type = Column(String, nullable=False)  # create/deposit/withdraw/transfer_in/transfer_out
    amount = Column(Numeric(18, 8), nullable=False)
    meta = Column(Text, nullable=True)     # JSON string for extras
    created_at = Column(DateTime, default=now_utc, nullable=False)

    wallet = relationship("Wallet", back_populates="txns")


def init_db():
    Base.metadata.create_all(engine)


@app.teardown_appcontext
def remove_session(exception=None):
    SessionLocal.remove()

init_db()

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def decimal_to_float(x):
    return float(x) if isinstance(x, Decimal) else x

def tx_to_dict(t: Transaction, with_wallet=False):
    data = {
        "id": t.id,
        "wallet_id": t.wallet_id,
        "type": t.type,
        "amount": decimal_to_float(t.amount),
        "created_at": t.created_at.isoformat() + "Z",
    }
    if t.meta:
        try:
            data["meta"] = json.loads(t.meta)
        except Exception:
            data["meta"] = t.meta
    if with_wallet and t.wallet:
        data["wallet"] = {"id": t.wallet.id, "name": t.wallet.name, "balance": decimal_to_float(t.wallet.balance)}
    return data

def require_api_key(func):
    # Decorator to protect endpoints with X-Api-Key
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Api-Key", "")
        if not API_TOKEN or token != API_TOKEN:
            return jsonify({"ok": False, "error": "Unauthorized (X-Api-Key)"}), 401
        return func(*args, **kwargs)
    return wrapper

# ------------------------------------------------------------------------------
# Legacy / Utility Routes
# ------------------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({"ok": True, "time": now_utc().isoformat() + "Z"})

@app.get("/__ping")
def __ping():
    routes_count = len([r for r in app.url_map.iter_rules()])
    has_debug_llm = bool(NONO_LLM_KEY and NONO_LLM_URL and NONO_LLM_MODEL)
    return jsonify({
        "ok": True,
        "routes_count": routes_count,
        "has_debug_llm": has_debug_llm
    })

@app.get("/whoami")
def whoami():
    # Backwards-compat: header X-Auth-Token must match WHOAMI_TOKEN
    hdr = request.headers.get("X-Auth-Token", "")
    return jsonify({
        "ok": bool(WHOAMI_TOKEN and hdr == WHOAMI_TOKEN),
        "you": "nono-user",
        "matched": bool(WHOAMI_TOKEN and hdr == WHOAMI_TOKEN)
    })

@app.get("/nono/api/env_names")
@require_api_key
def env_names():
    names = sorted([
        n for n in os.environ.keys()
        if n.startswith("NONO_") or n in ["API_TOKEN", "WHOAMI_TOKEN", "DATABASE_URL"]
    ])
    return jsonify({"names": names})

@app.get("/nono/api/debug_llm")
@require_api_key
def debug_llm():
    return jsonify({
        "has_key": bool(NONO_LLM_KEY),
        "has_url": bool(NONO_LLM_URL),
        "model": NONO_LLM_MODEL or "",
        "ok": bool(NONO_LLM_KEY and NONO_LLM_URL and NONO_LLM_MODEL)
    })

@app.post("/nono/api/ask")
@require_api_key
def nono_ask():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt") or request.form.get("prompt") or ""
    if not prompt:
        return jsonify({"ok": False, "error": "Missing 'prompt'"}), 400

    if not (NONO_LLM_KEY and NONO_LLM_URL and NONO_LLM_MODEL):
        return jsonify({"ok": False, "error": "LLM not configured"}), 500

    try:
        headers = {
            "Authorization": f"Bearer {NONO_LLM_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": NONO_LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You are Nono, a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(NONO_LLM_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        j = resp.json()
        # OpenAI-style response parsing
        content = (
            j.get("choices", [{}])[0]
             .get("message", {})
             .get("content", "")
        )
        return jsonify({"ok": True, "model": NONO_LLM_MODEL, "answer": content})
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 502

# ------------------------------------------------------------------------------
# Wallet Core
# ------------------------------------------------------------------------------
@app.post("/wallet/create")
@require_api_key
def wallet_create():
    sess = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "name required"}), 400

        w = Wallet(name=name, balance=Decimal("0"))
        sess.add(w)
        sess.flush()

        t = Transaction(wallet_id=w.id, type="create", amount=Decimal("0"), meta=json.dumps({"name": name}))
        sess.add(t)
        sess.commit()

        return jsonify({"ok": True, "wallet": {"id": w.id, "name": w.name, "balance": decimal_to_float(w.balance)}})
    except IntegrityError:
        sess.rollback()
        return jsonify({"ok": False, "error": "wallet name already exists"}), 409
    finally:
        sess.close()

@app.get("/wallet/balance")
@require_api_key
def wallet_balance():
    wallet_id = request.args.get("wallet_id", "")
    if not wallet_id:
        return jsonify({"ok": False, "error": "wallet_id required"}), 400
    sess = SessionLocal()
    try:
        w = sess.get(Wallet, wallet_id)
        if not w:
            return jsonify({"ok": False, "error": "wallet not found"}), 404
        return jsonify({"ok": True, "wallet": {"id": w.id, "name": w.name, "balance": decimal_to_float(w.balance)}})
    finally:
        sess.close()

@app.post("/wallet/deposit")
@require_api_key
def wallet_deposit():
    sess = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        wallet_id = data.get("wallet_id", "")
        amount = Decimal(str(data.get("amount", "0")))
        if not wallet_id or amount <= 0:
            return jsonify({"ok": False, "error": "wallet_id and positive amount required"}), 400

        w = sess.get(Wallet, wallet_id)
        if not w:
            return jsonify({"ok": False, "error": "wallet not found"}), 404

        w.balance = (w.balance or Decimal("0")) + amount
        t = Transaction(wallet_id=w.id, type="deposit", amount=amount, meta=None)
        sess.add(t)
        sess.commit()
        return jsonify({"ok": True, "balance": decimal_to_float(w.balance), "tx": tx_to_dict(t)})
    finally:
        sess.close()

@app.post("/wallet/withdraw")
@require_api_key
def wallet_withdraw():
    sess = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        wallet_id = data.get("wallet_id", "")
        amount = Decimal(str(data.get("amount", "0")))
        if not wallet_id or amount <= 0:
            return jsonify({"ok": False, "error": "wallet_id and positive amount required"}), 400

        w = sess.get(Wallet, wallet_id)
        if not w:
            return jsonify({"ok": False, "error": "wallet not found"}), 404

        if w.balance < amount:
            return jsonify({"ok": False, "error": "insufficient funds"}), 400

        w.balance = w.balance - amount
        t = Transaction(wallet_id=w.id, type="withdraw", amount=amount, meta=None)
        sess.add(t)
        sess.commit()
        return jsonify({"ok": True, "balance": decimal_to_float(w.balance), "tx": tx_to_dict(t)})
    finally:
        sess.close()

@app.post("/wallet/transfer")
@require_api_key
def wallet_transfer():
    sess = SessionLocal()
    try:
        data = request.get_json(silent=True) or {}
        from_id = data.get("from_wallet_id", "")
        to_id = data.get("to_wallet_id", "")
        amount = Decimal(str(data.get("amount", "0")))
        if not from_id or not to_id or amount <= 0:
            return jsonify({"ok": False, "error": "from_wallet_id, to_wallet_id and positive amount required"}), 400
        if from_id == to_id:
            return jsonify({"ok": False, "error": "cannot transfer to same wallet"}), 400

        wf = sess.get(Wallet, from_id)
        wt = sess.get(Wallet, to_id)
        if not wf or not wt:
            return jsonify({"ok": False, "error": "wallet not found"}), 404
        if wf.balance < amount:
            return jsonify({"ok": False, "error": "insufficient funds"}), 400

        wf.balance = wf.balance - amount
        wt.balance = (wt.balance or Decimal("0")) + amount

        meta_out = {"to": wt.id, "to_name": wt.name}
        meta_in  = {"from": wf.id, "from_name": wf.name}

        t_out = Transaction(wallet_id=wf.id, type="transfer_out", amount=amount, meta=json.dumps(meta_out))
        t_in  = Transaction(wallet_id=wt.id, type="transfer_in", amount=amount, meta=json.dumps(meta_in))

        sess.add_all([t_out, t_in])
        sess.commit()
        return jsonify({
            "ok": True,
            "from_balance": decimal_to_float(wf.balance),
            "to_balance": decimal_to_float(wt.balance),
            "tx_out": tx_to_dict(t_out),
            "tx_in": tx_to_dict(t_in),
        })
    finally:
        sess.close()

# ------------------------------------------------------------------------------
# Transactions: list + filters + CSV export
# ------------------------------------------------------------------------------
@app.get("/transactions")
@require_api_key
def transactions_list():
    sess = SessionLocal()
    try:
        q = sess.query(Transaction).order_by(Transaction.created_at.desc())

        wallet_id = request.args.get("wallet_id")
        tx_type = request.args.get("type")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        page = int(request.args.get("page", "1"))
        page_size = min(200, int(request.args.get("page_size", "50")))

        if wallet_id:
            q = q.filter(Transaction.wallet_id == wallet_id)
        if tx_type:
            q = q.filter(Transaction.type == tx_type)
        if date_from:
            try:
                df = datetime.fromisoformat(date_from.replace("Z", "").replace("z", ""))
                q = q.filter(Transaction.created_at >= df)
            except Exception:
                pass
        if date_to:
            try:
                dt = datetime.fromisoformat(date_to.replace("Z", "").replace("z", ""))
                q = q.filter(Transaction.created_at <= dt)
            except Exception:
                pass

        total = q.count()
        items = q.offset((page - 1) * page_size).limit(page_size).all()
        return jsonify({
            "ok": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [tx_to_dict(t) for t in items],
        })
    finally:
        sess.close()

@app.get("/transactions/export.csv")
@require_api_key
def transactions_export_csv():
    sess = SessionLocal()
    try:
        q = sess.query(Transaction).order_by(Transaction.created_at.desc())

        wallet_id = request.args.get("wallet_id")
        tx_type = request.args.get("type")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")

        if wallet_id:
            q = q.filter(Transaction.wallet_id == wallet_id)
        if tx_type:
            q = q.filter(Transaction.type == tx_type)
        if date_from:
            try:
                df = datetime.fromisoformat(date_from.replace("Z", "").replace("z", ""))
                q = q.filter(Transaction.created_at >= df)
            except Exception:
                pass
        if date_to:
            try:
                dt = datetime.fromisoformat(date_to.replace("Z", "").replace("z", ""))
                q = q.filter(Transaction.created_at <= dt)
            except Exception:
                pass

        rows = q.all()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "wallet_id", "type", "amount", "created_at", "meta"])
        for t in rows:
            writer.writerow([
                t.id,
                t.wallet_id,
                t.type,
                str(t.amount),
                t.created_at.isoformat() + "Z",
                t.meta or "",
            ])
        mem = io.BytesIO(buf.getvalue().encode("utf-8"))
        mem.seek(0)
        return send_file(
            mem,
            mimetype="text/csv",
            as_attachment=True,
            download_name="transactions.csv"
        )
    finally:
        sess.close()

# ------------------------------------------------------------------------------
# Simple Dashboard (pass ?key=YOUR_API_TOKEN to view)
# ------------------------------------------------------------------------------
DASHBOARD_HTML = """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Nono Wallet Dashboard</title>
<style>
 body{background:#0b0f14;color:#e6edf3;font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0}
 header{padding:16px 20px;border-bottom:1px solid #1f2833;display:flex;justify-content:space-between;align-items:center}
 h1{font-size:18px;margin:0}
 main{padding:20px;max-width:1100px;margin:0 auto}
 .card{background:#111827;border:1px solid #1f2833;border-radius:16px;padding:16px;margin-bottom:16px;box-shadow:0 4px 14px rgba(0,0,0,.25)}
 label{display:block;margin:4px 0 8px}
 input,select,button{background:#0b1220;color:#e6edf3;border:1px solid #243241;border-radius:10px;padding:8px 10px}
 table{width:100%;border-collapse:collapse;margin-top:12px}
 th,td{border-bottom:1px solid #243241;padding:8px;text-align:right}
 th{opacity:.8}
 .row{display:flex;gap:12px;flex-wrap:wrap}
 .row > *{flex:1}
 .muted{opacity:.7}
 .pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#0f172a;border:1px solid #243241;font-size:12px}
 a{color:#8ab4ff}
</style>
</head>
<body>
<header>
  <h1>نونو-والِت • Dashboard</h1>
  <div class="muted">أدخل الصفحة هكذا: <code>/dashboard?key=YOUR_API_TOKEN</code></div>
</header>
<main>
  <div class="card">
    <div class="row">
      <div>
        <label>Wallet ID</label>
        <input id="walletId" placeholder="uuid" />
      </div>
      <div>
        <label>الرصيد</label>
        <button id="btnBalance">عرض الرصيد</button>
        <span id="balance" class="pill"></span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="row">
      <div>
        <label>عملية</label>
        <select id="op">
          <option value="deposit">إيداع</option>
          <option value="withdraw">سحب</option>
          <option value="transfer">تحويل</option>
        </select>
      </div>
      <div>
        <label>المبلغ</label>
        <input id="amount" type="number" step="0.00000001" value="10" />
      </div>
      <div id="toWalletWrap" style="display:none">
        <label>إلى Wallet ID</label>
        <input id="toWalletId" placeholder="uuid" />
      </div>
      <div style="align-self:end">
        <button id="btnDo">تنفيذ</button>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="row">
      <div>
        <label>تصفية السجل</label>
        <input id="fltWallet" placeholder="wallet_id (اختياري)" />
      </div>
      <div>
        <label>النوع</label>
        <select id="fltType">
          <option value="">الكل</option>
          <option>create</option><option>deposit</option><option>withdraw</option>
          <option>transfer_in</option><option>transfer_out</option>
        </select>
      </div>
      <div>
        <label>من تاريخ</label>
        <input id="fltFrom" type="datetime-local" />
      </div>
      <div>
        <label>إلى تاريخ</label>
        <input id="fltTo" type="datetime-local" />
      </div>
      <div style="align-self:end">
        <button id="btnLoad">تحميل</button>
        <a id="lnkCsv" href="#" target="_blank">تصدير CSV</a>
      </div>
    </div>
    <table id="tbl">
      <thead><tr><th>الوقت</th><th>المعرف</th><th>Wallet</th><th>النوع</th><th>المبلغ</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</main>

<script>
const params = new URLSearchParams(location.search);
const KEY = params.get('key') || '';
function hdr(){ return {"X-Api-Key": KEY}; }
function fmt(x){ return new Intl.NumberFormat('en-US',{maximumFractionDigits:8}).format(x); }

const op = document.getElementById('op');
op.addEventListener('change', ()=>{
  document.getElementById('toWalletWrap').style.display = (op.value==='transfer')?'block':'none';
});

document.getElementById('btnBalance').onclick = async ()=>{
  const id = document.getElementById('walletId').value.trim();
  if(!id) return alert('Wallet ID?');
  const r = await fetch(`/wallet/balance?wallet_id=${encodeURIComponent(id)}`, {headers: hdr()});
  const j = await r.json();
  document.getElementById('balance').textContent = j.ok ? fmt(j.wallet.balance) : (j.error||'!');
};

document.getElementById('btnDo').onclick = async ()=>{
  const id = document.getElementById('walletId').value.trim();
  const amount = parseFloat(document.getElementById('amount').value||'0');
  const kind = op.value;
  let url = '', body = {};
  if(kind==='transfer'){
    const toId = document.getElementById('toWalletId').value.trim();
    url = '/wallet/transfer';
    body = {from_wallet_id:id, to_wallet_id:toId, amount};
  }else{
    url = '/wallet/'+kind;
    body = {wallet_id:id, amount};
  }
  const r = await fetch(url,{method:'POST',headers:{...hdr(),"Content-Type":"application/json"},body:JSON.stringify(body)});
  const j = await r.json();
  if(!j.ok) alert(j.error||'خطأ'); else alert('تمت العملية');
};

document.getElementById('btnLoad').onclick = loadTx;
async function loadTx(){
  const w = document.getElementById('fltWallet').value.trim();
  const t = document.getElementById('fltType').value;
  const f = document.getElementById('fltFrom').value ? new Date(document.getElementById('fltFrom').value).toISOString() : '';
  const to = document.getElementById('fltTo').value ? new Date(document.getElementById('fltTo').value).toISOString() : '';
  const qs = new URLSearchParams();
  if(w) qs.set('wallet_id', w);
  if(t) qs.set('type', t);
  if(f) qs.set('date_from', f);
  if(to) qs.set('date_to', to);

  const r = await fetch(`/transactions?${qs.toString()}`, {headers: hdr()});
  const j = await r.json();
  const tbody = document.querySelector('#tbl tbody');
  tbody.innerHTML = '';
  if(j.ok){
    for(const it of j.items){
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${new Date(it.created_at).toLocaleString()}</td>
        <td class="muted">${it.id}</td>
        <td class="muted">${it.wallet_id}</td>
        <td>${it.type}</td>
        <td>${fmt(it.amount)}</td>`;
      tbody.appendChild(tr);
    }
  }
  // CSV link
  const lnk = document.getElementById('lnkCsv');
  lnk.href = `/transactions/export.csv?${qs.toString()}`;
  lnk.onclick = (e)=>{ e.preventDefault(); window.open(lnk.href + (qs.toString()?'&':'?') + 'dl=1', '_blank'); }
}
</script>
</body>
</html>
"""

@app.get("/dashboard")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

# ------------------------------------------------------------------------------
# App entry
# ------------------------------------------------------------------------------
@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "name": "nono-wallet",
        "time": now_utc().isoformat() + "Z",
        "routes": [str(r) for r in app.url_map.iter_rules()]
    })

# WSGI entry
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
