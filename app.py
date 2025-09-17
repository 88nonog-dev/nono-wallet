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

# احفظ رابط قاعدة البيانات بمتغير ENV اسمه DATABASE_URL (Railway/Postgres/SQLite)
# مثال محلي: export DATABASE_URL=sqlite:///nono_wallet.db
db_url = os.environ.get("DATABASE_URL", "sqlite:///nono_wallet.db")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# موديلات قاعدة البيانات
# -----------------------------------------------------------------------------
class Wallet(db.Model):
    __tablename__ = "wallets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    balance = db.Column(db.Numeric(38, 8), nullable=False, default=0)
    # قد لا يكون موجود عندك عمود name – الراوت يتعامل مع غيابه
    # name = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey("wallets.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(38, 8), nullable=False)
    type = db.Column(db.String(16), nullable=False)  # "deposit" | "withdraw" | "transfer"
    meta = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

# إنشاء الجداول لو أول مرة
with app.app_context():
    db.create_all()

# -----------------------------------------------------------------------------
# هيلبرز
# -----------------------------------------------------------------------------
def table_has_column(db_engine, table_name: str, column_name: str) -> bool:
    """يتحقق إذا العمود موجود بجدول معيّن (حتى ما يفشل لو العمود ناقص)."""
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

# -----------------------------------------------------------------------------
# راوتات أساسية
# -----------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "nono-wallet", "db": bool(db.engine)}), 200

@app.route("/whoami", methods=["GET"])
def whoami():
    # اختياري: اقرأ هيدر بسيط للتعريف
    uid = request.headers.get("X-User", "guest")
    return jsonify({"ok": True, "user": uid}), 200

# -----------------------------------------------------------------------------
# /wallet/create — مقاوم للأعمدة الناقصة
# -----------------------------------------------------------------------------
@app.route("/wallet/create", methods=["POST"])
def create_wallet():
    """
    JSON input:
    {
      "user_id": "u_123",            (إلزامي)
      "initial_deposit": 100.0,      (اختياري)
      "name": "Main Wallet"          (اختياري؛ إذا عمود name مو موجود نتجاهله)
    }
    """
    data = request.get_json(silent=True) or {}

    user_id = (data.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    initial_deposit = data.get("initial_deposit", 0)
    initial_deposit = to_decimal(initial_deposit)
    if initial_deposit is None or initial_deposit < 0:
        return jsonify({"ok": False, "error": "invalid initial_deposit"}), 400

    desired_name = data.get("name")

    try:
        # 1) أنشئ المحفظة (رصيد صفر بالبداية)
        wallet = Wallet(user_id=user_id, balance=Decimal("0"))
        db.session.add(wallet)
        db.session.flush()  # نحصل على wallet.id قبل الكومِت

        # 2) اسم المحفظة إن وُجد العمود
        name_applied = False
        if desired_name:
            if table_has_column(db.engine, Wallet.__tablename__, "name"):
                # حتى لو الموديل ما بيه attribute، نقدر نحدّث SQL خام
                db.session.execute(
                    f'UPDATE {Wallet.__tablename__} SET name = :name WHERE id = :wid',
                    {"name": str(desired_name)[:120], "wid": wallet.id}
                )
                name_applied = True
            else:
                app.logger.warning("Column `name` not found on wallets — skipping name assignment.")

        # 3) إيداع أولي إن وجد
        tx_id = None
        if initial_deposit > 0:
            tx = Transaction(
                wallet_id=wallet.id,
                amount=initial_deposit,
                type="deposit",
                meta={"reason": "initial_deposit"}
            )
            db.session.add(tx)
            wallet.balance = wallet.balance + initial_deposit
            db.session.flush()
            tx_id = tx.id

        # 4) تثبيت
        db.session.commit()

        return jsonify({
            "ok": True,
            "wallet": {
                "id": wallet.id,
                "user_id": wallet.user_id,
                "balance": str(wallet.balance),
                "name_set": name_applied
            },
            "initial_deposit_tx_id": tx_id
        }), 201

    except Exception as e:
        db.session.rollback()
        app.logger.exception("wallet/create failed")
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# -----------------------------------------------------------------------------
# تشغيل محلي
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
