"""
models/shelter.py — Shelter model.

Represents one physical shelter location.
Latitude and longitude are stored so we can calculate distances later
using the Haversine formula (Stage 7).

Status values:
  active   — open and accepting people
  inactive — temporarily closed
  full     — at or over safe capacity
  damaged  — damaged and not safe to use
  closed   — permanently closed
"""

from datetime import datetime
from extensions import db


class Shelter(db.Model):
    __tablename__ = 'shelters'

    id                = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name              = db.Column(db.String(150), nullable=False, unique=True)
    address           = db.Column(db.String(300), nullable=False)

    # Location — stored as decimal degrees for Haversine calculation
    latitude          = db.Column(db.Numeric(9, 6), nullable=False)
    longitude         = db.Column(db.Numeric(9, 6), nullable=False)

    # Capacity fields
    max_capacity      = db.Column(db.Integer, nullable=False)
    current_occupancy = db.Column(db.Integer, nullable=False, default=0)

    # Operational status
    status = db.Column(
        db.Enum('active', 'inactive', 'full', 'damaged', 'closed',
                name='shelter_status'),
        nullable=False,
        default='active'
    )

    # Optional per-shelter safe occupancy limit (percentage, e.g. 85).
    # If NULL, the application uses the global default from config.
    safe_limit_pct = db.Column(db.Integer, nullable=True)

    # The shelter manager — references a user with shelter_manager role
    managed_by = db.Column(db.Integer, db.ForeignKey('users.id',
                           ondelete='SET NULL'), nullable=True)

    notes      = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    # One shelter → one facility record
    facility = db.relationship(
        'ShelterFacility',
        backref='shelter',
        uselist=False,       # uselist=False → one-to-one
        cascade='all, delete-orphan'
    )

    # One shelter → one resource record
    resource = db.relationship(
        'Resource',
        backref='shelter',
        uselist=False,
        cascade='all, delete-orphan'
    )

    # One shelter → many occupancy history records
    occupancy_history = db.relationship(
        'OccupancyHistory',
        backref='shelter',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # One shelter → many allocations
    allocations = db.relationship(
        'Allocation',
        backref='shelter',
        lazy='dynamic'
    )

    # One shelter → many alerts
    alerts = db.relationship(
        'Alert',
        backref='shelter',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        db.Index('idx_shelters_location', 'latitude', 'longitude'),
        db.Index('idx_shelters_status', 'status'),
    )

    def __repr__(self):
        return (f'<Shelter id={self.id} name={self.name!r} '
                f'occupancy={self.current_occupancy}/{self.max_capacity}>')

    # ── Operational & Capacity helpers ────────────────────────────────────────

    @property
    def is_operational(self):
        """Returns True if the shelter status is active and operational."""
        return self.status == 'active'

    @property
    def available_capacity(self):
        """Available Capacity = Maximum Capacity - Current Occupancy."""
        from services.capacity import calculate_available_capacity
        return calculate_available_capacity(self.max_capacity, self.current_occupancy)

    @property
    def occupancy_pct(self):
        """Occupancy Percentage = (Current Occupancy / Maximum Capacity) * 100."""
        from services.capacity import calculate_occupancy_percentage
        return calculate_occupancy_percentage(self.current_occupancy, self.max_capacity)

    @property
    def safe_limit(self):
        """Effective safe occupancy limit (per-shelter override or global config default)."""
        if self.safe_limit_pct is not None and self.safe_limit_pct > 0:
            return self.safe_limit_pct
        from services.capacity import get_configured_safe_limit_pct
        return get_configured_safe_limit_pct()

    @property
    def safe_capacity(self):
        """Planning Capacity = Maximum Capacity * (Safe Limit % / 100)."""
        from services.capacity import calculate_safe_capacity
        return calculate_safe_capacity(self.max_capacity, self.safe_limit)

    @property
    def safe_available_capacity(self):
        """Safe Available Capacity = Safe Planning Capacity - Current Occupancy."""
        from services.capacity import calculate_safe_available_capacity
        return calculate_safe_available_capacity(self.max_capacity, self.current_occupancy, self.safe_limit)

    @property
    def capacity_status(self):
        """
        Capacity severity level based on configurable thresholds:
          0  - 60%  -> safe
          61 - 80%  -> moderate
          81 - 95%  -> high
          96 - 100% -> critical
          Above 100%-> overcrowded
        """
        from services.capacity import determine_occupancy_status
        return determine_occupancy_status(self.occupancy_pct)

    @property
    def capacity_status_label(self):
        """Human-readable display name for capacity status."""
        from services.capacity import get_status_label
        return get_status_label(self.capacity_status)

    @property
    def capacity_badge_class(self):
        """CSS class for capacity badge."""
        from services.capacity import get_status_badge_class
        return get_status_badge_class(self.capacity_status)

    @property
    def capacity_metrics(self):
        """Comprehensive dictionary of all capacity and occupancy metrics."""
        from services.capacity import get_shelter_capacity_metrics
        return get_shelter_capacity_metrics(self)

    @property
    def status_label(self):
        return {
            'active':   'Active',
            'inactive': 'Inactive',
            'full':     'Full',
            'damaged':  'Damaged',
            'closed':   'Closed',
        }.get(self.status, self.status.title())

