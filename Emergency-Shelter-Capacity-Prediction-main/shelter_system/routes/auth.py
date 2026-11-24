"""
routes/auth.py — Authentication routes.

Routes:
  GET/POST  /auth/login     — Sign in
  GET/POST  /auth/register  — Create a citizen account (self-service)
  GET       /auth/logout    — Sign out (requires login)

Design decisions:
  - Public registration creates CITIZEN accounts only.
    Responder, manager, authority and admin accounts are created
    by an administrator in Stage 12 (admin panel).
  - Passwords are hashed with bcrypt (Flask-Bcrypt).
  - Flask-Login manages the session cookie.
  - The 'next' query parameter is respected after login so users
    are redirected back to the page they were trying to reach.
  - Open redirect is prevented: 'next' must start with '/'.
"""

import re
from urllib.parse import urlsplit
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db, bcrypt
from models.user import User

auth_bp = Blueprint('auth', __name__)

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


def _is_safe_redirect(target: str) -> bool:
    """
    Validate redirect target to prevent Open Redirect (CWE-601).
    Guarantees the target is an internal relative path and cannot redirect
    to external hosts via protocol-relative URLs (//) or backslashes (/\\).
    """
    if not target:
        return False
    # Disallow protocol-relative URLs and backslash evasions
    if target.startswith('//') or target.startswith('/\\'):
        return False
    if not target.startswith('/'):
        return False
    # Parse URL components and ensure no scheme or network location (host) is present
    parsed = urlsplit(target)
    return not parsed.scheme and not parsed.netloc


# ── Login ──────────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Sign in with email and password."""
    # If already signed in, send to home
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        # ── Validate presence & lengths (Bcrypt DoS guard) ─────────────────
        if not email or not password:
            flash('Email and password are required.', 'danger')
            return render_template('auth/login.html', email=email)

        if len(password) > 128 or len(email) > 120:
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', email=email)

        # ── Look up user ───────────────────────────────────────────────────
        user = User.query.filter_by(email=email).first()

        # Intentionally use the same message for "not found" and "wrong password"
        # to avoid leaking whether an email is registered (security best practice)
        if user is None or not bcrypt.check_password_hash(user.password_hash, password):
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', email=email)

        # ── Check account is active ────────────────────────────────────────
        if not user.is_active:
            flash('This account has been deactivated. Contact an administrator.', 'danger')
            return render_template('auth/login.html', email=email)

        # ── Session fixation prevention & Sign in ──────────────────────────
        session.clear()
        login_user(user, remember=remember)

        # Redirect to the originally requested page (if safe)
        next_page = request.args.get('next', '')
        if next_page and _is_safe_redirect(next_page):
            return redirect(next_page)
        return redirect(url_for('main.index'))

    return render_template('auth/login.html')


# ── Register ───────────────────────────────────────────────────────────────────

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    Self-service registration — creates a CITIZEN account.

    Operational accounts (responder, manager, authority, admin) are
    created by an administrator in the admin panel (Stage 12).
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        full_name        = request.form.get('full_name', '').strip()
        email            = request.form.get('email', '').strip().lower()
        password         = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # ── Collect all validation errors before returning ─────────────────
        errors = []

        if not full_name:
            errors.append('Full name is required.')
        elif len(full_name) > 120:
            errors.append('Full name must be 120 characters or fewer.')

        if not email:
            errors.append('Email address is required.')
        elif len(email) > 120:
            errors.append('Email must be 120 characters or fewer.')
        elif not EMAIL_REGEX.match(email):
            errors.append('Enter a valid email address.')

        if not password:
            errors.append('Password is required.')
        elif len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        elif len(password) > 128:
            errors.append('Password must be 128 characters or fewer.')

        if password and confirm_password != password:
            errors.append('Passwords do not match.')

        # Only check for duplicate email if everything else is valid
        if not errors:
            existing = User.query.filter_by(email=email).first()
            if existing:
                errors.append('An account with this email address already exists.')

        if errors:
            for msg in errors:
                flash(msg, 'danger')
            # Return form values so the user doesn't retype everything
            return render_template('auth/register.html',
                                   full_name=full_name, email=email)

        # ── Create user ────────────────────────────────────────────────────
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        user   = User(full_name=full_name, email=email,
                      password_hash=hashed, role='citizen')
        db.session.add(user)
        db.session.commit()

        flash('Account created. Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


# ── Logout ─────────────────────────────────────────────────────────────────────

@auth_bp.route('/logout')
def logout():
    """Sign out the current user, clear session, delete remember cookie, and redirect to login."""
    if current_user.is_authenticated:
        logout_user()
    session.clear()
    flash('You have been signed out successfully.', 'info')
    resp = redirect(url_for('auth.login'))

    # Explicitly clear remember-me cookie to prevent automatic re-authentication
    cookie_name = current_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    resp.delete_cookie(cookie_name)

    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp
