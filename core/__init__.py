"""
core — iConnect Application Factory.

Calling create_app() returns a fully configured Flask application instance
with all blueprints registered and error handlers set.
"""

from flask import render_template

from .config import get_config


def create_app():
    from flask import Flask

    app = Flask(__name__, template_folder="../templates")
    app.config.from_object(get_config())

    # ── Blueprints ─────────────────────────────────────────────────────────
    from .auth   import auth_bp
    from .posts  import posts_bp
    from .social import social_bp
    from .views  import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(social_bp)

    # ── Template globals ───────────────────────────────────────────────────
    from .helpers import generate_csrf_token
    app.jinja_env.globals["csrf_token"] = generate_csrf_token

    # ── Error handlers ─────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(exc):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def request_entity_too_large(exc):
        return render_template("413.html"), 413

    @app.errorhandler(500)
    def internal_error(exc):
        return render_template("500.html"), 500

    return app
