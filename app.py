from flask import Flask, jsonify, request

# إنشاء التطبيق
app = Flask(__name__)

# مسار فحص الصحة
@app.get("/health")
def health():
    return jsonify(ok=True)

# مسار التحقق من الهوية
@app.get("/whoami")
def whoami():
    token = request.headers.get("X-Auth-Token", "")
    if not token:
        return jsonify(ok=False, error="missing token"), 401
    return jsonify(ok=True, token=token)

# تشغيل محلي (اختياري)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
