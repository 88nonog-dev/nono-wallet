from flask import Flask, jsonify, request
import uuid

app = Flask(__name__)

# =========================
# Health
# =========================
@app.get("/health")
def health():
    return jsonify(ok=True)

# =========================
# Whoami (simple header echo)
# =========================
@app.get("/whoami")
def whoami():
    token = request.headers.get("X-Auth-Token", "")
    if not token:
        return jsonify(ok=False, error="missing token"), 401
    return jsonify(ok=True, token=token)

# =========================
# In-memory store (prototype)
# NOTE: Volatile; resets on restart/redeploy
# =========================
wallets = {}  # {wallet_id: {"balance": float}}

# =========================
# Create wallet
# =========================
@app.post("/wallet/create")
def create_wallet():
    wallet_id = str(uuid.uuid4())
    wallets[wallet_id] = {"balance": 0.0}
    return jsonify(ok=True, wallet_id=wallet_id, balance=wallets[wallet_id]["balance"])

# =========================
# Get balance
# =========================
@app.get("/wallet/balance")
def wallet_balance():
    wallet_id = request.args.get("wallet_id", "")
    if not wallet_id or wallet_id not in wallets:
        return jsonify(ok=False, error="wallet_not_found"), 404
    return jsonify(ok=True, wallet_id=wallet_id, balance=wallets[wallet_id]["balance"])

# =========================
# Deposit
# =========================
@app.post("/wallet/deposit")
def wallet_deposit():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id", "")
    amount = data.get("amount", None)

    if not wallet_id or wallet_id not in wallets:
        return jsonify(ok=False, error="wallet_not_found"), 404
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="invalid_amount"), 400
    if amount <= 0:
        return jsonify(ok=False, error="amount_must_be_positive"), 400

    wallets[wallet_id]["balance"] += amount
    return jsonify(ok=True, wallet_id=wallet_id, balance=wallets[wallet_id]["balance"])

# =========================
# Withdraw
# =========================
@app.post("/wallet/withdraw")
def wallet_withdraw():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id", "")
    amount = data.get("amount", None)

    if not wallet_id or wallet_id not in wallets:
        return jsonify(ok=False, error="wallet_not_found"), 404
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="invalid_amount"), 400
    if amount <= 0:
        return jsonify(ok=False, error="amount_must_be_positive"), 400
    if wallets[wallet_id]["balance"] < amount:
        return jsonify(ok=False, error="insufficient_funds"), 400

    wallets[wallet_id]["balance"] -= amount
    return jsonify(ok=True, wallet_id=wallet_id, balance=wallets[wallet_id]["balance"])

# =========================
# Transfer (wallet -> wallet)
# =========================
@app.post("/wallet/transfer")
def wallet_transfer():
    data = request.get_json(silent=True) or {}
    from_id = data.get("from_wallet_id", "")
    to_id = data.get("to_wallet_id", "")
    amount = data.get("amount", None)

    if not from_id or from_id not in wallets:
        return jsonify(ok=False, error="from_wallet_not_found"), 404
    if not to_id or to_id not in wallets:
        return jsonify(ok=False, error="to_wallet_not_found"), 404
    if from_id == to_id:
        return jsonify(ok=False, error="same_wallet"), 400

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="invalid_amount"), 400
    if amount <= 0:
        return jsonify(ok=False, error="amount_must_be_positive"), 400
    if wallets[from_id]["balance"] < amount:
        return jsonify(ok=False, error="insufficient_funds"), 400

    wallets[from_id]["balance"] -= amount
    wallets[to_id]["balance"] += amount

    return jsonify(
        ok=True,
        from_wallet_id=from_id,
        to_wallet_id=to_id,
        amount=amount,
        from_balance=wallets[from_id]["balance"],
        to_balance=wallets[to_id]["balance"],
    )

# =========================
# Local run (Railway uses gunicorn)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
