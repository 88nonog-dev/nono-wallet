# -*- coding: utf-8 -*-
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime

from flask import Flask, request, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect

# -----------------------------------------------------------------------------
# إعداد التطبيق + قاعدة البيانات
# -----------------------------------------------------------------------------
app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL", "sqlite:///nono_wallet.db")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# حماية API بالمفتاح
# -----------------------------------------------------------------------------
API_KEY = os.environ.get("API_KEY")  # نضبطه في Railway Variables
from flask import abort

@app.before_request
def require_api_key():
    # اسمح لطريق الصحة بدون مفتاح
    if request.path == "/health":
        return
    # إذا ما محدد API_KEY في البيئة، نسمح (وضع التطوير)
    if not API_KEY:
        return
    provided = request.headers.get("X-API-Key")
    if provided != API_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

# -----------------------------------------------------------------------------
# الموديلات
# -----------------------------------------------------------------------------
class Wallet(db.Model):
    __tablename__ = "wallets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True, unique=True)
    balance = db.Column(db.Numeric(38, 8), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(38, 8), nullable=False)
    type = db.Column(db.String(16), nullable=False)
    meta = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

with app.app_context():
    db.create_all()

# -----------------------------------------------------------------------------
# مساعدين
# -----------------------------------------------------------------------------
def table_has_column(db_engine, table_name: str, column_name: str) -> bool:
    try:
        insp = inspect(db_engine)
        cols = [c["name"] for c in insp.get_columns(table_name)]
        return column_name in cols
    except Exception as e:
        try:
            current_app.logger.warning(f"[has_column] failed: {e}")
        except Exception:
            pass
        return False

def to_decimal(x):
    try:
        return Decimal(str(x))
    except (InvalidOperation, TypeError):
        return None

def get_or_create_wallet(user_id: str) -> Wallet:
    w = Wallet.query.filter_by(user_id=user_id).first()
    if w:
        return w
    w = Wallet(user_id=user_id, balance=Decimal("0"))
    db.session.add(w)
    db.session.flush()
    return w

def wallet_json(w: Wallet):
    return {"id": w.id, "user_id": w.user_id, "balance": str(w.balance)}

# -----------------------------------------------------------------------------
# صحّة الخدمة
# -----------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "nono-wallet", "db": True}), 200

# -----------------------------------------------------------------------------
# إنشاء محفظة
# -----------------------------------------------------------------------------
@app.route("/wallet/create", methods=["POST"])
def create_wallet():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    initial_deposit = to_decimal(data.get("initial_deposit", 0))
    if initial_deposit is None or initial_deposit < 0:
        return jsonify({"ok": False, "error": "invalid initial_deposit"}), 400

    desired_name = data.get("name")
    try:
        wallet = Wallet.query.filter_by(user_id=user_id).first()
        if wallet is None:
            wallet = Wallet(user_id=user_id, balance=Decimal("0"))
            db.session.add(wallet)
            db.session.flush()

        name_applied = False
        if desired_name and table_has_column(db.engine, Wallet.__tablename__, "name"):
            db.session.execute(
                f'UPDATE {Wallet.__tablename__} SET name = :name WHERE id = :wid',
                {"name": str(desired_name)[:120], "wid": wallet.id}
            )
            name_applied = True

        tx_id = None
        if initial_deposit and initial_deposit > 0:
            tx = Transaction(wallet_id=wallet.id, amount=initial_deposit, type="deposit", meta={"reason": "initial_deposit"})
            db.session.add(tx)
            wallet.balance = wallet.balance + initial_deposit
            db.session.flush()
            tx_id = tx.id

        db.session.commit()
        return jsonify({
            "ok": True,
            "wallet": {"id": wallet.id, "user_id": wallet.user_id, "balance": str(wallet.balance), "name_set": name_applied},
            "initial_deposit_tx_id": tx_id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# -----------------------------------------------------------------------------
# إيداع
# -----------------------------------------------------------------------------
@app.route("/wallet/deposit", methods=["POST"])
def wallet_deposit():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("user_id") or "").strip()
    amount = to_decimal(data.get("amount", 0))

    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400
    if amount is None or amount <= 0:
        return jsonify({"ok": False, "error": "amount must be > 0"}), 400

    try:
        w = get_or_create_wallet(user_id)
        tx = Transaction(wallet_id=w.id, amount=amount, type="deposit")
        db.session.add(tx)
        w.balance = w.balance + amount
        db.session.commit()
        return jsonify({"ok": True, "wallet": wallet_json(w)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# -----------------------------------------------------------------------------
# سحب
# -----------------------------------------------------------------------------
@app.route("/wallet/withdraw", methods=["POST"])
def wallet_withdraw():
    data = request.get_json(silent=True) or {}
    user_id = (data.get("user_id") or "").strip()
    amount = to_decimal(data.get("amount", 0))

    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400
    if amount is None or amount <= 0:
        return jsonify({"ok": False, "error": "amount must be > 0"}), 400

    try:
        w = Wallet.query.filter_by(user_id=user_id).first()
        if w is None:
            return jsonify({"ok": False, "error": "wallet_not_found"}), 404

        if w.balance < amount:
            return jsonify({"ok": False, "error": "insufficient_funds", "balance": str(w.balance)}), 400

        tx = Transaction(wallet_id=w.id, amount=-amount, type="withdraw")
        db.session.add(tx)
        w.balance = w.balance - amount
        db.session.commit()
        return jsonify({"ok": True, "wallet": wallet_json(w)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# -----------------------------------------------------------------------------
# تحويل
# -----------------------------------------------------------------------------
@app.route("/wallet/transfer", methods=["POST"])
def wallet_transfer():
    data = request.get_json(silent=True) or {}
    from_uid = (data.get("from_user_id") or "").strip()
    to_uid = (data.get("to_user_id") or "").strip()
    amount = to_decimal(data.get("amount", 0))

    if not from_uid or not to_uid:
        return jsonify({"ok": False, "error": "from_user_id and to_user_id are required"}), 400
    if from_uid == to_uid:
        return jsonify({"ok": False, "error": "same_source_and_target"}), 400
    if amount is None or amount <= 0:
        return jsonify({"ok": False, "error": "amount must be > 0"}), 400

    try:
        sender = Wallet.query.filter_by(user_id=from_uid).first()
        if sender is None:
            return jsonify({"ok": False, "error": "sender_wallet_not_found"}), 404

        if sender.balance < amount:
            return jsonify({"ok": False, "error": "insufficient_funds", "balance": str(sender.balance)}), 400

        receiver = get_or_create_wallet(to_uid)

        tx_out = Transaction(wallet_id=sender.id, amount=-amount, type="transfer_out", meta={"to_user_id": to_uid})
        tx_in = Transaction(wallet_id=receiver.id, amount=amount, type="transfer_in", meta={"from_user_id": from_uid})
        db.session.add_all([tx_out, tx_in])

        sender.balance = sender.balance - amount
        receiver.balance = receiver.balance + amount

        db.session.commit()
        return jsonify({"ok": True, "from_wallet": wallet_json(sender), "to_wallet": wallet_json(receiver)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# -----------------------------------------------------------------------------
# رصيد محفظة
# -----------------------------------------------------------------------------
@app.route("/wallet/balance", methods=["GET"])
def wallet_balance():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400
    w = Wallet.query.filter_by(user_id=user_id).first()
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404
    return jsonify({"ok": True, "wallet": wallet_json(w)}), 200
# -----------------------------------------------------------------------------
# سجل الحركات
# -----------------------------------------------------------------------------
@app.route("/wallet/transactions", methods=["GET"])
def wallet_transactions():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    w = Wallet.query.filter_by(user_id=user_id).first()
    if not w:
        return jsonify({"ok": False, "error": "wallet_not_found"}), 404

    # باراميترات اختيارية: limit و offset
    try:
        limit = int(request.args.get("limit", "20"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_pagination"}), 400

    q = (Transaction.query
         .filter_by(wallet_id=w.id)
         .order_by(Transaction.id.desc())
         .offset(offset)
         .limit(min(max(limit, 1), 100)))  # 1..100

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
# صفحة الجذر (Root)
# -----------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "service": "nono-wallet", "message": "Service OK"}), 200

# -----------------------------------------------------------------------------
# تشغيل محلي
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
