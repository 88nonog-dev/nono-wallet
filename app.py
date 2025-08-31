from flask import Flask, jsonify, request

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify(ok=True)

@app.get("/whoami")
def whoami():
    token = request.headers.get("X-Auth-Token", "")
    if not token:
        return jsonify(ok=False, error="missing token"), 401
    return jsonify(ok=True, token=token)

# مسار مؤقت لعرض كل المسارات المسجلة (للتشخيص)
@app.get("/__routes")
def list_routes():
    try:
        routes = sorted([str(r.rule) for r in app.url_map.iter_rules()])
        return jsonify(ok=True, routes=routes)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

if __name__ == "__main__":
    # للركض المحلي فقط، Railway يستخدم gunicorn
    app.run(host="0.0.0.0", port=8080)
