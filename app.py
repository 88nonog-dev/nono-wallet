from flask import Flask, jsonify, request
import uuid

app = Flask(__name__)

# =========================
# مسار فحص الصحة
# =========================
@app.get("/health")
def health():
    return jsonify(ok=True)

# =========================
# مسار التحقق من الهوية
# =========================
@app.get("/whoami")
def whoami():
    token = request.headers.get("X-Auth-Token", "")
    if not token:
        return jsonify(ok=False, error="missing token"), 401
    return jsonify(ok=True, token=token)

# =========================
# خازن بسيط للمحافظ بالميموري
# =========================
wallets = {}

# =========================
# إنشاء محفظة جديدة
# =========================
@app.post("/wallet/create")
def create_wallet():
    wallet_id = str(uuid.uuid4())  # يولّد رقم محفظة فريد
    wallets[wallet_id] = {"balance": 0}
    return jsonify(ok=True, wallet_id=wallet_id, balance=0)

# =========================
# عرض رصيد محفظة
# =========================
@app.get("/wallet/balance")
def wallet_balance():
    wallet_id = request.args.get("wallet_id", "")
    if not wallet_id or wallet_id not in wallets:
        return jsonify(ok=False, error="wallet_not_found"), 404
    return jsonify(ok=True, wallet_id=wallet_id, balance=wallets[wallet_id]["balance"])

# =========================
# تشغيل محلي فقط (Railway يستخدم gunicorn)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
