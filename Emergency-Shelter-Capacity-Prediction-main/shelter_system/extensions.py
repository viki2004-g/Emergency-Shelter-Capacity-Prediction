"""
extensions.py — Shared Flask extensions.

All extension instances live here so any module can import them
without creating circular imports.

    from extensions import db, login_manager, bcrypt
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_wtf.csrf import CSRFProtect

# ── SQLAlchemy ────────────────────────────────────────────────────────────────
db = SQLAlchemy()

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager = LoginManager()

# Where to redirect unauthenticated users who try to access a protected route
login_manager.login_view = 'auth.login'

# The flash message shown when redirected to login
login_manager.login_message = 'Please sign in to access this page.'
login_manager.login_message_category = 'warning'

# ── Flask-Bcrypt ──────────────────────────────────────────────────────────────
bcrypt = Bcrypt()

# ── CSRF Protection ───────────────────────────────────────────────────────────
csrf = CSRFProtect()

