from flask import Flask, jsonify, request
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import create_engine, String, Numeric
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
import uuid

# =========================
# DB Setup
# =========================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")

# SSL for Postgres on Railway if needed
connect_args = {}
if DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy recommends 'postgresql://' scheme; adjust if old format
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Create engine
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 18 digits total, 2 بعد الفارزة — مناسب للمبالغ النقدية
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))

Base.metadata.create_all(bind=engine)

# =========================
# Flask App
# =========================
app = Flask(__name__)

def d(val) -> Decimal:
    """Parse to Decimal with 2 digits."""
    if isinstance(val, Decimal):
        q = val
    else:
        q = Decimal(str(val))
    return q.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# =========================
# Health & Whoami
# =========================
@app.get("/health")
def health():
    return jsonify(ok=True)

@app.get("/whoami")
def whoami():
    token = request.headers.get("X-Auth-Token", "")
    if not token:
        return jsonify(ok=False, error="missing token"), 401
    return jsonify(ok=True, token=token)

# =========================
# Wallet Endpoints (Persistent via DB)
# =========================
@app.post("/wallet/create")
def create_wallet():
    db = SessionLocal()
    try:
        wallet_id = str(uuid.uuid4())
        w = Wallet(id=wallet_id, balance=d("0"))
        db.add(w)
        db.commit()
        return jsonify(ok=True, wallet_id=wallet_id, balance=float(w.balance))
    finally:
        db.close()

@app.get("/wallet/balance")
def wallet_balance():
    wallet_id = request.args.get("wallet_id", "")
    if not wallet_id:
        return jsonify(ok=False, error="wallet_id_required"), 400

    db = SessionLocal()
    try:
        w = db.get(Wallet, wallet_id)
        if not w:
            return jsonify(ok=False, error="wallet_not_found"), 404
        return jsonify(ok=True, wallet_id=wallet_id, balance=float(w.balance))
    finally:
        db.close()

@app.post("/wallet/deposit")
def wallet_deposit():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id", "")
    amount = data.get("amount", None)

    if not wallet_id:
        return jsonify(ok=False, error="wallet_id_required"), 400
    try:
        amount = d(amount)
    except (TypeError, InvalidOperation):
        return jsonify(ok=False, error="invalid_amount"), 400
    if amount <= 0:
        return jsonify(ok=False, error="amount_must_be_positive"), 400

    db = SessionLocal()
    try:
        w = db.get(Wallet, wallet_id)
        if not w:
            return jsonify(ok=False, error="wallet_not_found"), 404
        w.balance = d(w.balance + amount)
        db.commit()
        return jsonify(ok=True, wallet_id=wallet_id, balance=float(w.balance))
    finally:
        db.close()

@app.post("/wallet/withdraw")
def wallet_withdraw():
    data = request.get_json(silent=True) or {}
    wallet_id = data.get("wallet_id", "")
    amount = data.get("amount", None)

    if not wallet_id:
        return jsonify(ok=False, error="wallet_id_required"), 400
    try:
        amount = d(amount)
    except (TypeError, InvalidOperation):
        return jsonify(ok=False, error="invalid_amount"), 400
    if amount <= 0:
        return jsonify(ok=False, error="amount_must_be_positive"), 400

    db = SessionLocal()
    try:
        w = db.get(Wallet, wallet_id)
        if not w:
            return jsonify(ok=False, error="wallet_not_found"), 404
        if w.balance < amount:
            return jsonify(ok=False, error="insufficient_funds"), 400
        w.balance = d(w.balance - amount)
        db.commit()
        return jsonify(ok=True, wallet_id=wallet_id, balance=float(w.balance))
    finally:
        db.close()

@app.post("/wallet/transfer")
def wallet_transfer():
    data = request.get_json(silent=True) or {}
    from_id = data.get("from_wallet_id", "")
    to_id = data.get("to_wallet_id", "")
    amount = data.get("amount", None)

    if not from_id or not to_id:
        return jsonify(ok=False, error="wallet_ids_required"), 400
    if from_id == to_id:
        return jsonify(ok=False, error="same_wallet"), 400
    try:
        amount = d(amount)
    except (TypeError, InvalidOperation):
        return jsonify(ok=False, error="invalid_amount"), 400
    if amount <= 0:
        return jsonify(ok=False, error="amount_must_be_positive"), 400

    db = SessionLocal()
    try:
        # مع SQLAlchemy 2.0 هذا آمن ضمن معاملة
        w_from = db.get(Wallet, from_id)
        if not w_from:
            return jsonify(ok=False, error="from_wallet_not_found"), 404
        w_to = db.get(Wallet, to_id)
        if not w_to:
            return jsonify(ok=False, error="to_wallet_not_found"), 404

        if w_from.balance < amount:
            return jsonify(ok=False, error="insufficient_funds"), 400

        w_from.balance = d(w_from.balance - amount)
        w_to.balance = d(w_to.balance + amount)
        db.commit()

        return jsonify(
            ok=True,
            from_wallet_id=from_id,
            to_wallet_id=to_id,
            amount=float(amount),
            from_balance=float(w_from.balance),
            to_balance=float(w_to.balance),
        )
    finally:
        db.close()

# =========================
# Local run (Railway uses gunicorn)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
