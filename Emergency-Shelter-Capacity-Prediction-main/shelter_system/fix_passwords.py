"""
fix_passwords.py — Re-hash all seed user passwords using bcrypt.

Run this ONCE after implementing Flask-Bcrypt (Stage 3).
The seed passwords were originally hashed with werkzeug.security
in db_init.py. This script replaces them with bcrypt hashes
so the login system works correctly.

Usage:
  python fix_passwords.py

After running this, all seed users can log in with: Password@123
"""

from app import create_app
from extensions import db, bcrypt
from models.user import User

app = create_app()

with app.app_context():
    users = User.query.all()
    if not users:
        print("No users found. Run db_init.py first.")
    else:
        new_hash = bcrypt.generate_password_hash('Password@123').decode('utf-8')
        for user in users:
            user.password_hash = new_hash
        db.session.commit()
        print(f"Updated bcrypt hashes for {len(users)} user(s).")
        print("All seed users can now log in with: Password@123")
