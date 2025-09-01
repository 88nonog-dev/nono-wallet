from flask import Flask, jsonify, request, Response
import os
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone
import csv
from io import StringIO

from sqlalchemy import (
    create_engine, String, Numeric, DateTime, Enum, ForeignKey, select, desc, and_
)
from sqlalchemy.orm import (
    sessionmaker, DeclarativeBase, Mapped, mapped_column, relationship
)

# =========================
# DB Setup
# =========================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

# =========================
# Models
# =========================
class Wallet(Base):
    __tablename__ = "wallets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="wallet", cascade="all, delete-orphan"
    )

class TxType:
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"

ALLOWED_TYPES = {
    TxType.DEPOSIT, TxType.WITHDRAW, TxType.TRANSFER_IN, TxType.TRANSFER_OUT
}

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(String(64), ForeignKey("wallets.id"), index=True)
    type: Mapped[str] = mapped_column(
        Enum(TxType.DEPOSIT, TxType.WITHDRAW, TxType.TRANSFER_IN, TxType.TRANSFER_OUT, name="tx_type_enum"),
        nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    counterparty_wallet_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    wallet: Mapped[Wallet] = relationship(back_populates="transactions")

Base.metadata.create_all(bind=engine)

# =========================
# Flask App
# =========================
app = Flask(__name__)
# 🔐 API Key protection
API_TOKEN = os.getenv("API_TOKEN", "")

@app.before_request
def require_api_key():
    # مسارات مسموحة بدون مفتاح
    open_paths = {"/health", "/whoami"}
    if request.path in open_paths:
        return

    # التحقق من المفتاح
    key = request.headers.get("X-Api-Key", "")
    if not API_TOKEN or key != API_TOKEN:
        return jsonify(ok=False, error="unauthorized"), 401
# ---- helpers ----
def d(val) -> Decimal:
    """Normalize to Decimal(2dp)."""
    if isinstance(val, Decimal):
        q = val
    else:
        q = Decimal(str(val))
    return q.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def parse_iso8601(s: str | None) -> datetime | None:
    """Parse ISO8601; supports trailing 'Z'."""
    if not s:
        return None
    s = s.strip()
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def add_tx(db, wallet_id: str, tx_type: str, amount: Decimal, counterparty: str | None = None):
    tx = Transaction(
        id=str(uuid.uuid4()),
        wallet_id=wallet_id,
        type=tx_type,
        amount=d(amount),
        created_at=now_utc(),
        counterparty_wallet_id=counterparty,
    )
    db.add(tx)
    return tx

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
# Wallet Endpoints
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
        add_tx(db, wallet_id, TxType.DEPOSIT, amount)
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
        add_tx(db, wallet_id, TxType.WITHDRAW, amount)
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

        add_tx(db, from_id, TxType.TRANSFER_OUT, amount, counterparty=to_id)
        add_tx(db, to_id, TxType.TRANSFER_IN, amount, counterparty=from_id)

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
# Transactions: list + filters
# =========================
@app.get("/transactions")
def list_transactions():
    wallet_id = request.args.get("wallet_id", "")
    limit = request.args.get("limit", "50")
    offset = request.args.get("offset", "0")
    type_filter = request.args.get("type", "").strip().lower()
    from_s = request.args.get("from", "")
    to_s = request.args.get("to", "")

    if not wallet_id:
        return jsonify(ok=False, error="wallet_id_required"), 400

    try:
        limit_i = max(1, min(200, int(limit)))
        offset_i = max(0, int(offset))
    except ValueError:
        return jsonify(ok=False, error="invalid_pagination"), 400

    if type_filter and type_filter not in ALLOWED_TYPES:
        return jsonify(ok=False, error="invalid_type_filter"), 400

    dt_from = parse_iso8601(from_s) if from_s else None
    dt_to = parse_iso8601(to_s) if to_s else None
    if from_s and not dt_from:
        return jsonify(ok=False, error="invalid_from_datetime"), 400
    if to_s and not dt_to:
        return jsonify(ok=False, error="invalid_to_datetime"), 400

    db = SessionLocal()
    try:
        if not db.get(Wallet, wallet_id):
            return jsonify(ok=False, error="wallet_not_found"), 404

        conds = [Transaction.wallet_id == wallet_id]
        if type_filter:
            conds.append(Transaction.type == type_filter)
        if dt_from:
            conds.append(Transaction.created_at >= dt_from)
        if dt_to:
            conds.append(Transaction.created_at <= dt_to)

        stmt = (
            select(Transaction)
            .where(and_(*conds))
            .order_by(desc(Transaction.created_at))
            .limit(limit_i)
            .offset(offset_i)
        )
        rows = db.execute(stmt).scalars().all()
        items = [{
            "id": r.id,
            "wallet_id": r.wallet_id,
            "type": r.type,
            "amount": float(r.amount),
            "created_at": r.created_at.isoformat(),
            "counterparty_wallet_id": r.counterparty_wallet_id,
        } for r in rows]
        return jsonify(ok=True, wallet_id=wallet_id, count=len(items), items=items)
    finally:
        db.close()

# =========================
# Transactions: export CSV
# =========================
@app.get("/transactions/export.csv")
def export_transactions_csv():
    wallet_id = request.args.get("wallet_id", "")
    type_filter = request.args.get("type", "").strip().lower()
    from_s = request.args.get("from", "")
    to_s = request.args.get("to", "")

    if not wallet_id:
        return jsonify(ok=False, error="wallet_id_required"), 400
    if type_filter and type_filter not in ALLOWED_TYPES:
        return jsonify(ok=False, error="invalid_type_filter"), 400

    dt_from = parse_iso8601(from_s) if from_s else None
    dt_to = parse_iso8601(to_s) if to_s else None
    if from_s and not dt_from:
        return jsonify(ok=False, error="invalid_from_datetime"), 400
    if to_s and not dt_to:
        return jsonify(ok=False, error="invalid_to_datetime"), 400

    db = SessionLocal()
    try:
        if not db.get(Wallet, wallet_id):
            return jsonify(ok=False, error="wallet_not_found"), 404

        conds = [Transaction.wallet_id == wallet_id]
        if type_filter:
            conds.append(Transaction.type == type_filter)
        if dt_from:
            conds.append(Transaction.created_at >= dt_from)
        if dt_to:
            conds.append(Transaction.created_at <= dt_to)

        stmt = (
            select(Transaction)
            .where(and_(*conds))
            .order_by(desc(Transaction.created_at))
        )
        rows = db.execute(stmt).scalars().all()

        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "wallet_id", "type", "amount", "created_at", "counterparty_wallet_id"])
        for r in rows:
            writer.writerow([
                r.id,
                r.wallet_id,
                r.type,
                f"{float(r.amount):.2f}",
                r.created_at.isoformat(),
                r.counterparty_wallet_id or "",
            ])
        csv_data = buf.getvalue()
        buf.close()

        filename = f"transactions_{wallet_id}.csv"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(csv_data, mimetype="text/csv", headers=headers)
    finally:
        db.close()

# =========================
# Local run (Railway uses gunicorn)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
