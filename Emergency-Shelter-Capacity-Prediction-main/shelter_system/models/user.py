"""
models/user.py — User model.

Represents a system user with a role that controls what they can do.

Roles:
  admin           — manages users, roles and system settings
  authority       — monitors all shelters, reviews alerts and decisions
  responder       — submits group requests, runs recommendations, confirms allocations
  shelter_manager — updates occupancy, beds, food, water and facilities
  citizen         — searches for shelters and views availability

UserMixin gives Flask-Login the four properties it needs:
  is_authenticated, is_active, is_anonymous, get_id()
"""

from datetime import datetime
from flask_login import UserMixin
from extensions import db


# Human-readable display labels for each role (used in templates)
ROLE_LABELS = {
    'admin':           'Administrator',
    'authority':       'District Authority',
    'responder':       'Response Team',
    'shelter_manager': 'Shelter Manager',
    'citizen':         'Citizen',
}


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    full_name     = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(180), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(
                       db.Enum('admin', 'authority', 'responder',
                               'shelter_manager', 'citizen',
                               name='user_role'),
                       nullable=False,
                       default='citizen'
                   )
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ────────────────────────────────────────────────────────
    managed_shelters = db.relationship(
        'Shelter',
        foreign_keys='Shelter.managed_by',
        backref='manager',
        lazy='select'
    )
    submitted_requests = db.relationship(
        'ShelterRequest',
        foreign_keys='ShelterRequest.submitted_by',
        backref='submitter',
        lazy='dynamic'
    )
    recorded_history = db.relationship(
        'OccupancyHistory',
        foreign_keys='OccupancyHistory.recorded_by',
        backref='recorder',
        lazy='dynamic'
    )
    confirmed_allocations = db.relationship(
        'Allocation',
        foreign_keys='Allocation.confirmed_by',
        backref='confirmer',
        lazy='dynamic'
    )

    # ── Flask-Login requires get_id() ─────────────────────────────────────────
    def get_id(self):
        return str(self.id)

    # ── Role helpers ──────────────────────────────────────────────────────────
    @property
    def role_label(self):
        """Human-readable role name for display in templates."""
        return ROLE_LABELS.get(self.role, self.role.title())

    def has_role(self, *roles):
        """True if this user's role is in the given set."""
        return self.role in roles

    def can_manage_shelters(self):
        return self.role in ('shelter_manager', 'admin')

    def can_operate(self):
        """Responders and above can submit requests and run recommendations."""
        return self.role in ('responder', 'authority', 'admin')

    def can_monitor(self):
        """Authority and admin can see the full dashboard and all alerts."""
        return self.role in ('authority', 'admin')

    def __repr__(self):
        return f'<User id={self.id} email={self.email!r} role={self.role!r}>'

