# app.py
from flask import Flask, jsonify, request, abort
import os
from datetime import datetime, timezone

def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False  # يقبل /health و/health/

    WHOAMI_TOKEN = (os.getenv("WHOAMI_TOKEN") or "").strip()

    @app.get("/")
    def index():
        return jsonify(
            app="nono-wallet",
            status="running",
            time_utc=datetime.now(timezone.utc).isoformat()
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/whoami")
    def whoami():
        token = (request.args.get("token") or request.headers.get("X-Auth-Token") or "").strip()
        if not WHOAMI_TOKEN or token != WHOAMI_TOKEN:
            abort(404)
        return jsonify(app="nono-wallet", ok=True, time_utc=datetime.now(timezone.utc).isoformat())

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
