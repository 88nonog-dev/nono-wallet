import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, Response

from sqlalchemy import create_engine, text

# ------------------------------------------------------------------------------
# Flask app
# ------------------------------------------------------------------------------
app = Flask(__name__)
application = app  # Alias for gunicorn

# ------------------------------------------------------------------------------
# Database engine (robust)
# ------------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

def build_engine():
    url = DATABASE_URL
    if not url:
        # fallback محلي حتى ما يطيح السيرفر إذا ماكو DATABASE_URL
        return create_engine("sqlite:///nono_wallet.sqlite3", pool_pre_ping=True)
    # فرض SSL مع Neon
    if url.startswith("postgres") and "sslmode" not in url:
        if "?" in url:
            url = url + "&sslmode=require"
        else:
            url = url + "?sslmode=require"
    return create_engine(url, pool_pre_ping=True)

engine = build_engine()

# تأكد من وجود الجداول
def ensure_schema():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS wallets (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE,
            balance NUMERIC NOT NULL DEFAULT 0
        )"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            wallet_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            created_at TIMESTAMP NOT NULL,
            FOREIGN KEY(wallet_id) REFERENCES wallets(id)
        )"""))

try:
    ensure_schema()
except Exception as e:
    # لا تطيح التطبيق: خليه يكمل ويخدم /__ping، وباقي المسارات تبين الخطأ
    print("SCHEMA INIT WARNING:", e)

# ------------------------------------------------------------------------------
# Security: API Token
# ------------------------------------------------------------------------------
API_TOKEN = os.environ.get("API_TOKEN", "").strip()

def require_api_key(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Api-Key", "")
        if not API_TOKEN or token != API_TOKEN:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return func(*args, **kwargs)
    return wrapper

# ------------------------------------------------------------------------------
# Healthcheck (لا يلمس DB)
# ------------------------------------------------------------------------------
@app.get("/__ping")
def __ping():
    return jsonify({"ok": True})

@app.get("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})

# ------------------------------------------------------------------------------
# Wallet APIs
# ------------------------------------------------------------------------------
@app.post("/wallet/create")
@require_api_key
def wallet_create():
    data = request.get_json(silent=True) or {}
    name = data.get("name") or f"wallet-{uuid.uuid4().hex[:6]}"
    wallet_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO wallets (id, name, balance) VALUES (:id, :name, 0)"),
                     {"id": wallet_id, "name": name})
        conn.execute(text("""INSERT INTO transactions
            (id, wallet_id, type, amount, created_at)
            VALUES (:id,:wallet_id,:type,:amount,:ts)"""),
            {"id": str(uuid.uuid4()), "wallet_id": wallet_id, "type": "create", "amount": 0,
             "ts": datetime.utcnow()})
    return jsonify({"ok": True, "wallet": {"id": wallet_id, "name": name, "balance": 0}})

@app.post("/wallet/deposit")
@require_api_key
def wallet_deposit():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id")
    amount = float(data.get("amount") or 0)
    if not wallet_id or amount <= 0:
        return jsonify({"ok": False, "error": "wallet_id and positive amount required"}), 400
    with engine.begin() as conn:
        conn.execute(text("UPDATE wallets SET balance = balance + :amt WHERE id=:id"),
                     {"amt": amount, "id": wallet_id})
        conn.execute(text("""INSERT INTO transactions
            (id, wallet_id, type, amount, created_at)
            VALUES (:id,:wallet_id,:type,:amount,:ts)"""),
            {"id": str(uuid.uuid4()), "wallet_id": wallet_id, "type": "deposit", "amount": amount,
             "ts": datetime.utcnow()})
    return jsonify({"ok": True})

@app.post("/wallet/withdraw")
@require_api_key
def wallet_withdraw():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id")
    amount = float(data.get("amount") or 0)
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
            (id, wallet_id, type, amount, created_at)
            VALUES (:id,:wallet_id,:type,:amount,:ts)"""),
            {"id": str(uuid.uuid4()), "wallet_id": wallet_id, "type": "withdraw", "amount": amount,
             "ts": datetime.utcnow()})
    return jsonify({"ok": True})

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

@app.get("/transactions")
@require_api_key
def transactions_list():
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, wallet_id, type, amount, created_at
            FROM transactions
            ORDER BY created_at DESC
            LIMIT 200
        """)).mappings().all()
    return jsonify({"ok": True, "items": [dict(r) for r in rows]})

@app.get("/transactions/export.csv")
@require_api_key
def transactions_export():
    def gen():
        yield "id,wallet_id,type,amount,created_at\n"
        with engine.begin() as conn:
            for r in conn.execute(text("""
                SELECT id, wallet_id, type, amount, created_at
                FROM transactions
                ORDER BY created_at DESC
            """)):
                yield f"{r.id},{r.wallet_id},{r.type},{r.amount},{r.created_at}\n"
    return Response(gen(), mimetype="text/csv")

# ------------------------------------------------------------------------------
# Simple Dashboard (مختصر وواسع)
# ------------------------------------------------------------------------------
@app.get("/dashboard")
def dashboard():
    return DASHBOARD_HTML

DASHBOARD_HTML = """<!doctype html><html lang="ar" dir="rtl"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Nono Wallet Dashboard</title>
<style>
body{background:#0b0f14;color:#e6edf3;font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0}
header{padding:24px 32px;border-bottom:1px solid #1f2833;display:flex;justify-content:space-between;align-items:center}
main{padding:32px;max-width:1500px;margin:0 auto}
.card{background:#111827;border:1px solid #1f2833;border-radius:18px;padding:22px;margin-bottom:18px}
input,button{background:#0b1220;color:#e6edf3;border:1px solid #243241;border-radius:12px;padding:12px}
button{cursor:pointer;background:#0b5cff}
table{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}
th,td{border-bottom:1px solid #243241;padding:10px;text-align:right}
</style></head><body>
<header><h1>نونو-والِت • لوحة التحكم</h1></header>
<main>
  <div class="card">
    <label>API Token</label>
    <input id="apiKey" placeholder="ضع التوكن هنا" />
    <button onclick="localStorage.setItem('key',document.getElementById('apiKey').value);alert('Saved')">حفظ</button>
  </div>
  <div class="card">
    <button onclick="fetch('/wallet/create',{method:'POST',headers:{'X-Api-Key':localStorage.getItem('key'),'Content-Type':'application/json'},body:'{\"name\":\"main\"}'}).then(r=>r.json()).then(j=>alert(JSON.stringify(j)))">إنشاء محفظة</button>
  </div>
</main></body></html>"""

@app.get("/")
def home():
    return jsonify({"ok": True, "name": "nono-wallet", "time": datetime.utcnow().isoformat() + "Z"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
