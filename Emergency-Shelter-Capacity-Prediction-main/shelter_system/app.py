import os
from flask import Flask, render_template
from config import config_by_name
from extensions import db, login_manager, bcrypt, csrf


# ── Blueprint imports ─────────────────────────────────────────────────────────
from routes.main      import main_bp
from routes.auth      import auth_bp
from routes.shelters  import shelters_bp
from routes.requests  import requests_bp
from routes.recommend import recommend_bp
from routes.predict   import predict_bp
from routes.dashboard import dashboard_bp
from routes.alerts    import alerts_bp
from routes.admin     import admin_bp


def create_app(env_name: str = None) -> Flask:
    """
    Application factory — creates and configures the Flask app.
    Initializes all extensions and registers all blueprints.
    """
    app = Flask(__name__)

    # ── Configuration ─────────────────────────────────────────────────────────
    if env_name is None:
        env_name = os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config_by_name.get(env_name, config_by_name['development']))

    # ── Initialize extensions ─────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    # Import models so SQLAlchemy registers all tables and
    # Flask-Login can find the User model via the user_loader below.
    import models  # noqa: F401

    # ── Flask-Login: user loader ──────────────────────────────────────────────
    # Flask-Login calls this function on every request with the user ID
    # stored in the session cookie. We return the User object (or None).
    @login_manager.user_loader
    def load_user(user_id):
        from models.user import User
        return db.session.get(User, int(user_id))

    # ── Register blueprints ───────────────────────────────────────────────────
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp,      url_prefix='/auth')
    app.register_blueprint(shelters_bp,  url_prefix='/shelters')
    app.register_blueprint(requests_bp,  url_prefix='/requests')
    app.register_blueprint(recommend_bp, url_prefix='/recommend')
    app.register_blueprint(predict_bp,   url_prefix='/predict')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(alerts_bp,    url_prefix='/alerts')
    app.register_blueprint(admin_bp,     url_prefix='/admin')


    # ── Cache control ─────────────────────────────────────────────────────────
    # Prevents browsers from displaying cached authenticated pages after logout
    @app.after_request
    def add_header(response):
        if 'Cache-Control' not in response.headers:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # ── Error handlers ────────────────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return render_template('errors/400.html', error=e), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    return app


app = create_app()

if __name__ == '__main__':
    app.run()
