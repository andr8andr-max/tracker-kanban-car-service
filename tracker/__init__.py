import os

from flask import Flask, jsonify, send_from_directory

from . import config
from . import db
from .seed import run_seed

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")


def create_app(seed: bool = True) -> Flask:
    config.ensure_dirs()
    if seed:
        run_seed(demo=True)

    app = Flask(
        __name__,
        static_folder=STATIC_DIR,
        static_url_path="/static",
    )
    app.secret_key = config.secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )

    from .blueprints import admin, auth, board, notifications, orders, stats

    app.register_blueprint(auth.bp)
    app.register_blueprint(board.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(notifications.bp)
    app.register_blueprint(stats.bp)
    app.register_blueprint(admin.bp)

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "service": db.get_settings().get("service_name")})

    from flask import request as _req

    from .security import csrf_ok

    @app.before_request
    def _csrf_guard():
        if _req.path.startswith("/api/") and not csrf_ok():
            return (
                jsonify({"error": "bad_content_type", "message": "JSON body required"}),
                403,
            )
        return None

    @app.after_request
    def _no_cache(resp):
        if _req.path.startswith("/static/") or _req.path in ("/", "/index.html"):
            resp.headers["Cache-Control"] = "no-cache, max-age=0"
        return resp

    @app.errorhandler(404)
    def not_found(e):
        from flask import request

        if request.path.startswith("/api/"):
            return jsonify({"error": "not_found", "message": "Not found"}), 404
        return send_from_directory(STATIC_DIR, "index.html")

    @app.errorhandler(405)
    def method_not_allowed(e):
        if True:
            return jsonify({"error": "method_not_allowed", "message": "Method not allowed"}), 405

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "server_error", "message": "Internal server error"}), 500

    return app
