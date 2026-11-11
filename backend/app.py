"""Flask application factory. Serves the JSON API under /api and the static SPA frontend from /."""
from flask import Flask, jsonify, send_from_directory

from backend import config, db, seed
from backend.common import ApiError
from backend.routes import auth_kb, submissions


def create_app():
    import os
    if os.getenv("RENDER", "").lower() in ("true", "1") and config.SECRET_KEY == config.DEFAULT_SECRET_KEY:
        raise RuntimeError("Refusing to boot in production with default SECRET_KEY")

    app = Flask(__name__, static_folder=str(config.FRONTEND_DIR), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
    app.teardown_appcontext(db.close_db)
    db.init_db()
    with app.app_context():
        seed.seed_if_empty()

    app.register_blueprint(auth_kb.bp)
    app.register_blueprint(submissions.bp)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:;"
        )
        return response

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify({"error": e.message}), e.status

    @app.errorhandler(413)
    def too_big(_):
        return jsonify({"error": f"File too large (max {config.MAX_UPLOAD_MB} MB)"}), 413

    @app.errorhandler(404)
    def not_found(_):
        from flask import request
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(config.FRONTEND_DIR, "index.html")

    @app.errorhandler(Exception)
    def crash(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify({"error": e.description}), e.code
        app.logger.exception(e)
        return jsonify({"error": "Unexpected server error"}), 500

    @app.get("/")
    def index():
        return send_from_directory(config.FRONTEND_DIR, "index.html")

    return app


app = create_app()

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)), debug=False)
