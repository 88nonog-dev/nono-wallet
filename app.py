import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, Response

from sqlalchemy import create_engine, text

# Flask app
app = Flask(__name__)
application = app  # alias حتى يشتغل ويا wsgi.py

# Database (Neon PostgreSQL)
DATABASE_URL = os.environ.get("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Security: API Token
API_TOKEN = os.environ.get("API_TOKEN")

def require_api_key(func):
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Api-Key")
        if not token or token != API_TOKEN:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# Healthcheck
@app.route("/__ping")
def __ping():
    return jsonify({"ok": True})


# Wallet create
@app.route("/wallet/create", methods=["POST"])
@require_api_key
def wallet_create():
    data = request.get_json(force=True)
    name = data.get("name", "wallet")
    wallet_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO wallets (id, name, balance) VALUES (:id, :name, 0)"),
            {"id": wallet_id, "name": name},
        )
        conn.execute(
            text("INSERT INTO transactions (id, wallet_id, type, amount, created_at) VALUES (:id,:wallet_id,:type,:amount,:ts)"),
            {"id": str(uuid.uuid4()), "wallet_id": wallet_id, "type": "create", "amount": 0, "ts": datetime.utcnow()},
        )
    return jsonify({"ok": True, "wallet": {"id": wallet_id, "name": name, "balance": 0}})


# Deposit
@app.route("/wallet/deposit", methods=["POST"])
@require_api_key
def wallet_deposit():
    data = request.get_json(force=True)
    wallet_id = data.get("wallet_id")
    amount = float(data.get("amount", 0))
    if amount <= 0:
        return jsonify({"ok": False, "error": "Amount must be > 0"}), 400
    with engine.begin() as conn:
        conn.execute(text("UPDATE wallets SET balance = balance + :amt WHERE id=:id"), {"amt": amount, "id": wallet_id})
        conn.execute(
            text("INSERT INTO transactions (id, wallet_id, type, amount, created_at) VALUES (:id,:wallet_id,:type,:amount,:ts)"),
            {"id": str(uuid.uuid4()), "wallet_id": wallet_id, "type": "deposit", "amount": amount, "ts": datetime.utcnow()},
        )
    return jsonify({"ok": True})


# Withdraw
@app.route("/wallet/withdraw", methods=["POST"])
@require_api_key
def wallet_withdraw():
    data = request.get_json(force=True)
    wallet_id = data.get("wallet_id")
    amount = float(data.get("amount", 0))
    if amount <= 0:
        return jsonify({"ok": False, "error": "Amount must be > 0"}), 400
    with engine.begin() as conn:
        bal = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"), {"id": wallet_id}).scalar()
        if bal is None or bal < amount:
            return jsonify({"ok": False, "error": "Insufficient balance"}), 400
        conn.execute(text("UPDATE wallets SET balance = balance - :amt WHERE id=:id"), {"amt": amount, "id": wallet_id})
        conn.execute(
            text("INSERT INTO transactions (id, wallet_id, type, amount, created_at) VALUES (:id,:wallet_id,:type,:amount,:ts)"),
            {"id": str(uuid.uuid4()), "wallet_id": wallet_id, "type": "withdraw", "amount": amount, "ts": datetime.utcnow()},
        )
    return jsonify({"ok": True})


# Balance
@app.route("/wallet/balance")
@require_api_key
def wallet_balance():
    wallet_id = request.args.get("wallet_id")
    with engine.begin() as conn:
        bal = conn.execute(text("SELECT balance FROM wallets WHERE id=:id"), {"id": wallet_id}).scalar()
    return jsonify({"ok": True, "wallet": {"id": wallet_id, "balance": bal}})


# Transactions
@app.route("/transactions")
@require_api_key
def transactions_list():
    rows = []
    with engine.begin() as conn:
        result = conn.execute(text("SELECT id,wallet_id,type,amount,created_at FROM transactions ORDER BY created_at DESC LIMIT 50"))
        for r in result:
            rows.append(dict(r))
    return jsonify({"ok": True, "items": rows})


# Export CSV
@app.route("/transactions/export.csv")
@require_api_key
def transactions_export():
    def gen():
        yield "id,wallet_id,type,amount,created_at\n"
        with engine.begin() as conn:
            result = conn.execute(text("SELECT id,wallet_id,type,amount,created_at FROM transactions ORDER BY created_at DESC"))
            for r in result:
                yield f"{r.id},{r.wallet_id},{r.type},{r.amount},{r.created_at}\n"
    return Response(gen(), mimetype="text/csv")


# Dashboard (HTML wide layout)
@app.route("/dashboard")
def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
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
</style>
</head>
<body>
<header>
  <h1>نونو-والت • لوحة التحكم</h1>
</header>
<main>
  <div class="card">
    <label>API Token</label>
    <input id="apiKey" placeholder="ضع التوكن هنا" />
    <button onclick="localStorage.setItem('key',document.getElementById('apiKey').value);alert('Saved')">حفظ</button>
  </div>
  <div class="card">
    <button onclick="fetch('/wallet/create',{method:'POST',headers:{'X-Api-Key':localStorage.getItem('key'),'Content-Type':'application/json'},body:'{\"name\":\"main\"}'}).then(r=>r.json()).then(j=>alert(JSON.stringify(j)))">إنشاء محفظة</button>
  </div>
</main>
</body>
</html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
