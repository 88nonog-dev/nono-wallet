import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# -----------------------------------------------------------------------------
# تهيئة التطبيق وقاعدة البيانات
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///wallet.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# حماية API بالمفتاح
# -----------------------------------------------------------------------------
API_KEY = os.environ.get("API_KEY")  # نضبطه في Railway Variables

@app.before_request
def require_api_key():
    # أبيّض عبر أسماء الـ endpoints بدل المسار
    open_endpoints = {"health", "root"}  # root = صفحة الجذر "/", health = "/health"
    if request.endpoint in open_endpoints:
        return

    # إذا ماكو API_KEY بالبيئة (تطوير)، نسمح
    if not API_KEY:
        return

    # تحقق المفتاح
    provided = request.headers.get("X-API-Key")
    if provided != API_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

# -----------------------------------------------------------------------------
# الموديلات
# -----------------------------------------------------------------------------
class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), unique=True, nullable=False)
    balance = db.Column(db.Numeric(18, 8), default=0)
    name_set = db.Column(db.Boolean, default=False)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallet.id"), nullable=False)
    type = db.Column(db.String(32), nullable=False)
    amount = db.Column(db.Numeric(18, 8), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    meta = db.Column(db.JSON, default={})

# -----------------------------------------------------------------------------
# دوال مساعدة
# -----------------------------------------------------------------------------
def wallet_json(w: Wallet):
    return {"id": w.id, "user_id": w.user_id, "balance": str(w.balance)}

# -----------------------------------------------------------------------------
# Healthcheck
# -----------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    try:
        db.session.execute("SELECT 1")
        return jsonify({"ok": True, "db": True, "service": "nono-wallet"})
    except Exception as e:
        return jsonify({"ok": False, "db": False, "error": str(e)}), 500

# -----------------------------------------------------------------------------
# صفحة الجذر
# -----------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "service": "nono-wallet", "message": "Service OK"}), 200

# -----------------------------------------------------------------------------
# المسارات
# -----------------------------------------------------------------------------
@app.route("/wallet/create", methods=["POST"])
def create_wallet():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    w = Wallet.query.filter_by(user_id=user_id).first()
    if w:
        return jsonify({"ok": False, "error": "wallet_exists"}), 400

    w = Wallet(user_id=user_id, balance=data.get("initial_deposit", 0))
    db.session.add(w)
    if data.get("initial_deposit"):
        tx = Transaction(wallet_id=w.id, type="deposit",
                         amount=data["initial_deposit"],
                         meta={"reason": "initial_deposit"})
        db.session.add(tx)
    db.session.commit()
    return jsonify({"ok": True, "wallet": wallet_json(w)}), 200

@app.route("/wallet/deposit", methods=["POST"])
def deposit():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("user_id") or "").strip()
    amount = data.get("amount")
    if not user_id or not amount:
        return jsonify({"ok": False, "error": "missing_fields"}), 400

    w = Wallet.query.filter_by(user_id=user_id).first()
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    w.balance += amount
    tx = Transaction(wallet_id=w.id, type="deposit", amount=amount)
    db.session.add(tx)
    db.session.commit()
    return jsonify({"ok": True, "wallet": wallet_json(w)}), 200

@app.route("/wallet/withdraw", methods=["POST"])
def withdraw():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("user_id") or "").strip()
    amount = data.get("amount")
    if not user_id or not amount:
        return jsonify({"ok": False, "error": "missing_fields"}), 400

    w = Wallet.query.filter_by(user_id=user_id).first()
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    if w.balance < amount:
        return jsonify({"ok": False, "error": "insufficient_funds"}), 400

    w.balance -= amount
    tx = Transaction(wallet_id=w.id, type="withdraw", amount=amount)
    db.session.add(tx)
    db.session.commit()
    return jsonify({"ok": True, "wallet": wallet_json(w)}), 200

@app.route("/wallet/transfer", methods=["POST"])
def transfer():
    data = request.get_json(silent=True) or {}
    from_user = (data.get("from_user_id") or "").strip()
    to_user = (data.get("to_user_id") or "").strip()
    amount = data.get("amount")
    if not from_user or not to_user or not amount:
        return jsonify({"ok": False, "error": "missing_fields"}), 400

    from_w = Wallet.query.filter_by(user_id=from_user).first()
    to_w = Wallet.query.filter_by(user_id=to_user).first()
    if not from_w or not to_w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    if from_w.balance < amount:
        return jsonify({"ok": False, "error": "insufficient_funds"}), 400

    from_w.balance -= amount
    to_w.balance += amount
    db.session.add(Transaction(wallet_id=from_w.id, type="transfer", amount=amount, meta={"to": to_user}))
    db.session.add(Transaction(wallet_id=to_w.id, type="transfer", amount=amount, meta={"from": from_user}))
    db.session.commit()
    return jsonify({"ok": True, "from_wallet": wallet_json(from_w), "to_wallet": wallet_json(to_w)}), 200

@app.route("/wallet/balance", methods=["GET"])
def wallet_balance():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400
    w = Wallet.query.filter_by(user_id=user_id).first()
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404
    return jsonify({"ok": True, "wallet": wallet_json(w)}), 200

@app.route("/wallet/transactions", methods=["GET"])
def wallet_transactions():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    w = Wallet.query.filter_by(user_id=user_id).first()
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    try:
        limit = int(request.args.get("limit", "20"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_pagination"}), 400

    q = (Transaction.query
         .filter_by(wallet_id=w.id)
         .order_by(Transaction.id.desc())
         .offset(offset)
         .limit(min(max(limit, 1), 100)))
    items = []
    for t in q.all():
        items.append({
            "id": t.id,
            "type": t.type,
            "amount": str(t.amount),
            "created_at": t.created_at.isoformat(),
            "meta": t.meta
        })

    return jsonify({"ok": True, "wallet": wallet_json(w), "transactions": items}), 200

# -----------------------------------------------------------------------------
# تشغيل محلي
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
