import os
from datetime import datetime
from flask import Flask, request, jsonify, Response, render_template
from flask_sqlalchemy import SQLAlchemy

# -----------------------------------------------------------------------------
# ظ‚ط§ط¹ط¯ط© ط§ظ„ط¨ظٹط§ظ†ط§طھ (ظٹط¯ط¹ظ… PostgreSQL/SQLite) + طھطµط­ظٹط­ ط´ط§ط¦ط¹
# -----------------------------------------------------------------------------
def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///wallet.db")
    # Railway ط£ط­ظٹط§ظ†ظ‹ط§ ظٹظ…ط±ط± postgres:// ط¨ط¯ظ„ postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    # ظ„ظˆ ط£ط­ط¯ ظƒطھط¨ :PORT/ ظ†طµظٹط§ظ‹ ط¨ط¯ظ„ ط±ظ‚ظ…
    if ":PORT/" in url:
        url = url.replace(":PORT/", ":5432/", 1)
    return url

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = _build_db_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# ط§ظ„ظ…ظˆط¯ظٹظ„ط§طھ
# -----------------------------------------------------------------------------
class Wallet(db.Model):
    __tablename__ = "wallets"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Float, nullable=False, default=0.0)

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)       # ظ…ظˆط¬ط¨ = ط¥ظٹط¯ط§ط¹طŒ ط³ط§ظ„ط¨ = ط³ط­ط¨
    tx_type = db.Column(db.String(16), nullable=False) # deposit / withdraw
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    idempotency_key = db.Column(db.String(64), unique=True, nullable=True)

with app.app_context():
    db.create_all()

# -----------------------------------------------------------------------------
# ظ…ط³ط§ط¹ط¯ط§طھ
# -----------------------------------------------------------------------------
def require_api_token():
    api_token_env = os.getenv("API_TOKEN", "nonoSuperKey2025")
    sent = request.headers.get("X-Api-Token", "")
    if not api_token_env or sent != api_token_env:
        # ظ†ط±ط¬ظ‘ط¹ ظ‚ظٹظ…طھظٹظ† ظپظ‚ط·: False, ظˆ (Response, status) ظƒطھظ„ط© ظˆط­ط¯ط©
        return False, (jsonify({"ok": False, "error": "unauthorized"}), 401)
    return True, None

def get_idempotency_key():
    return request.headers.get("Idempotency-Key") or None

def wallet_required(wid: int):
    return db.session.get(Wallet, wid)

# -----------------------------------------------------------------------------
# طµط­ظ‘ط© ط§ظ„ط®ط¯ظ…ط© ظˆظ‡ظˆظٹط©
# -----------------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/whoami")
def whoami():
    token_env = os.getenv("WHOAMI_TOKEN", "WALLET2025OK")
    sent = request.headers.get("X-Auth-Token", "")
    if sent != token_env:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return jsonify({"ok": True, "service": "nono-wallet"})

# -----------------------------------------------------------------------------
# ط¥ظ†ط´ط§ط، ظ…ط­ظپط¸ط©
# -----------------------------------------------------------------------------
@app.route("/wallet/create", methods=["POST"])
def wallet_create():
    ok, resp = require_api_token()
    if not ok:
        return resp

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "Wallet").strip()
    try:
        initial = float(data.get("initial_balance") or 0)
    except Exception:
        initial = 0.0

    w = Wallet(name=name, balance=0.0)
    db.session.add(w)
    db.session.flush()  # ط­طھظ‰ ظ†ط£ط®ط° id ظ‚ط¨ظ„ ط§ظ„ظƒظˆظ…ظگطھ

    if initial != 0:
        t = Transaction(
            wallet_id=w.id,
            amount=abs(initial),
            tx_type="deposit",
            idempotency_key=get_idempotency_key(),
        )
        w.balance += abs(initial)
        db.session.add(t)

    db.session.commit()
    return jsonify({"ok": True, "wallet_id": w.id, "balance": w.balance})

# -----------------------------------------------------------------------------
# ط¥ظٹط¯ط§ط¹
# -----------------------------------------------------------------------------
@app.route("/wallet/deposit", methods=["POST"])
def wallet_deposit():
    ok, resp = require_api_token()
    if not ok:
        return resp

    data = request.get_json(silent=True) or {}
    wid = int(data.get("wallet_id", 0))
    amount = float(data.get("amount", 0))
    if wid <= 0 or amount <= 0:
        return jsonify({"ok": False, "error": "invalid_input"}), 400

    w = wallet_required(wid)
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    key = get_idempotency_key()
    if key:
        existed = db.session.query(Transaction.id).filter_by(idempotency_key=key).first()
        if existed:
            return jsonify({"ok": True, "wallet_id": w.id, "balance": w.balance})

    t = Transaction(wallet_id=w.id, amount=amount, tx_type="deposit", idempotency_key=key)
    w.balance += amount
    db.session.add(t)
    db.session.commit()
    return jsonify({"ok": True, "wallet_id": w.id, "balance": w.balance})

# -----------------------------------------------------------------------------
# ط³ط­ط¨
# -----------------------------------------------------------------------------
@app.route("/wallet/withdraw", methods=["POST"])
def wallet_withdraw():
    ok, resp = require_api_token()
    if not ok:
        return resp

    data = request.get_json(silent=True) or {}
    wid = int(data.get("wallet_id", 0))
    amount = float(data.get("amount", 0))
    if wid <= 0 or amount <= 0:
        return jsonify({"ok": False, "error": "invalid_input"}), 400

    w = wallet_required(wid)
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    if w.balance < amount:
        return jsonify({"ok": False, "error": "insufficient_funds"}), 400

    key = get_idempotency_key()
    if key:
        existed = db.session.query(Transaction.id).filter_by(idempotency_key=key).first()
        if existed:
            return jsonify({"ok": True, "wallet_id": w.id, "balance": w.balance})

    t = Transaction(wallet_id=w.id, amount=-amount, tx_type="withdraw", idempotency_key=key)
    w.balance -= amount
    db.session.add(t)
    db.session.commit()
    return jsonify({"ok": True, "wallet_id": w.id, "balance": w.balance})

# -----------------------------------------------------------------------------
# ط§ظ„ط±طµظٹط¯
# -----------------------------------------------------------------------------
@app.route("/wallet/balance")
def wallet_balance():
    try:
        wid = int(request.args.get("wallet_id", "0"))
    except Exception:
        return jsonify({"ok": False, "error": "invalid_wallet_id"}), 400

    if wid <= 0:
        return jsonify({"ok": False, "error": "invalid_wallet_id"}), 400

    w = wallet_required(wid)
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    return jsonify({"ok": True, "wallet_id": w.id, "balance": w.balance})

# -----------------------------------------------------------------------------
# ط§ظ„ط³ط¬ظ„
# -----------------------------------------------------------------------------
@app.route("/transactions")
def transactions():
    try:
        wid = int(request.args.get("wallet_id", "0"))
    except Exception:
        wid = 0

    q = Transaction.query
    if wid > 0:
        q = q.filter_by(wallet_id=wid)

    items = q.order_by(Transaction.created_at.desc()).limit(500).all()

    def _row(t: Transaction):
        return {
            "id": t.id,
            "wallet_id": t.wallet_id,
            "amount": t.amount,
            "tx_type": t.tx_type,
            "created_at": t.created_at.isoformat(),
        }

    return jsonify({"ok": True, "items": [_row(t) for t in items]})

# -----------------------------------------------------------------------------
# طھطµط¯ظٹط± CSV
# -----------------------------------------------------------------------------
@app.route("/export/csv")
def export_csv():
    try:
        wid = int(request.args.get("wallet_id", "0"))
    except Exception:
        wid = 0

    q = Transaction.query
    if wid > 0:
        q = q.filter_by(wallet_id=wid)
    items = q.order_by(Transaction.created_at.asc()).all()

    rows = ["id;wallet_id;amount;tx_type;created_at"]
    for t in items:
        rows.append(f"{t.id};{t.wallet_id};{t.amount};{t.tx_type};{t.created_at.isoformat()}")

    data = "\n".join(rows)
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="wallet_{wid or "all"}.csv"'},
    )

# -----------------------------------------------------------------------------
# ط§ظ„ظˆط§ط¬ظ‡ط© ط§ظ„ط£ظ…ط§ظ…ظٹط© â€” ظ…ط¤ظ‚طھظ‹ط§ ظ†طµ ط¨ط³ظٹط· ط­طھظ‰ ظ†ط«ط¨طھ ط§ظ„ظ†ط´ط± ط£ط®ط¶ط±
# (ظ†ط±ط¬ط¹ ظ†ط±ط¨ط· dashboard.html ط¨ط¹ط¯ ط§ظ„ط§ط³طھظ‚ط±ط§ط±)
# -----------------------------------------------------------------------------
@app.route("/")
def dashboard():
        return render_template("dashboard.html", api_token=os.getenv("API_TOKEN",""))

# طھط´ط؛ظٹظ„ ظ…ط­ظ„ظٹ ظپظ‚ط· (Railway ظٹط³طھط®ط¯ظ… gunicorn: app:app)
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
