"""
utils/decorators.py — Role-based access control decorators.

Usage in any route:
    from utils.decorators import role_required

    @shelters_bp.route('/create')
    @role_required('admin', 'shelter_manager')
    def create_shelter():
        ...

How it works:
  1. @login_required (from Flask-Login) checks the user is signed in.
     If not → redirect to login page with a flash message.
  2. role_required then checks the role.
     If the role doesn't match → abort(403) Forbidden.

This means:
  - Unauthenticated users   → redirected to /auth/login
  - Wrong-role users        → 403 Forbidden page
"""

from functools import wraps
from flask import abort
from flask_login import current_user, login_required


def role_required(*roles):
    """
    Decorator that restricts a route to users with one of the given roles.

    Always apply this AFTER any route decorator:
        @blueprint.route(...)
        @role_required('admin')       ← correct order
        def my_view(): ...

    Parameters:
        *roles — one or more role strings from the ENUM:
                 'admin', 'authority', 'responder', 'shelter_manager', 'citizen'
    """
    def decorator(f):
        @wraps(f)
        @login_required              # unauthenticated → redirect to login
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                # User is logged in but does not have the required role
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ── Convenience decorators for common role combinations ────────────────────────
# These make routes more readable: @responder_required instead of
# @role_required('responder', 'authority', 'admin')

def admin_required(f):
    """Only system administrators."""
    return role_required('admin')(f)


def authority_required(f):
    """District authority and admins — for monitoring and alerts."""
    return role_required('authority', 'admin')(f)


def responder_required(f):
    """Response team, authority and admin — for operational actions."""
    return role_required('responder', 'authority', 'admin')(f)


def manager_required(f):
    """Shelter managers and admin — for shelter/occupancy updates."""
    return role_required('shelter_manager', 'admin')(f)
