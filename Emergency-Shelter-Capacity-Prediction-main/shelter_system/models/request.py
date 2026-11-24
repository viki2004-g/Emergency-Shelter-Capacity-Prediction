"""
models/request.py — ShelterRequest model.

A shelter request is submitted when a group of displaced people needs
to be placed in a shelter. It describes:
  - requesting user and team
  - how many people are in the group (must be > 0)
  - where they currently are (latitude/longitude)
  - breakdown counts: injured, elderly, children (>= 0)
  - accessibility requirements, medical requirements, other special requirements
  - status and creation timestamp

Status flow:
  pending → allocated (all placed in one shelter)
          → partially_allocated (group split across shelters)
          → cancelled
"""

from datetime import datetime
from extensions import db


# Status display labels
REQUEST_STATUS_LABELS = {
    'pending':             'Pending Allocation',
    'allocated':           'Allocated',
    'partially_allocated': 'Partially Allocated',
    'cancelled':           'Cancelled',
}

REQUEST_STATUS_BADGES = {
    'pending':             'req-badge-pending',
    'allocated':           'req-badge-allocated',
    'partially_allocated': 'req-badge-partial',
    'cancelled':           'req-badge-cancelled',
}


class ShelterRequest(db.Model):
    __tablename__ = 'shelter_requests'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Who submitted this request (FK to users)
    submitted_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='RESTRICT'),
        nullable=False
    )

    group_size   = db.Column(db.Integer, nullable=False)

    # Where the group currently is
    latitude     = db.Column(db.Numeric(9, 6), nullable=False)
    longitude    = db.Column(db.Numeric(9, 6), nullable=False)
    location_name= db.Column(db.String(200), nullable=True)

    # Requesting team / organization & contact phone
    requesting_team = db.Column(db.String(150), nullable=True)
    contact_phone   = db.Column(db.String(50), nullable=True)

    # People counts Breakdown (must be >= 0)
    injured_count   = db.Column(db.Integer, nullable=False, default=0)
    elderly_count   = db.Column(db.Integer, nullable=False, default=0)
    children_count  = db.Column(db.Integer, nullable=False, default=0)

    # Special requirements
    accessibility_requirements = db.Column(db.Text, nullable=True)
    medical_requirements       = db.Column(db.Text, nullable=True)
    other_special_requirements = db.Column(db.Text, nullable=True)

    # Boolean flags for recommendation engine constraint filtering
    has_injured  = db.Column(db.Boolean, nullable=False, default=False)
    has_elderly  = db.Column(db.Boolean, nullable=False, default=False)
    has_disabled = db.Column(db.Boolean, nullable=False, default=False)
    has_children = db.Column(db.Boolean, nullable=False, default=False)

    status = db.Column(
        db.Enum('pending', 'allocated', 'partially_allocated', 'cancelled',
                name='request_status'),
        nullable=False,
        default='pending'
    )

    notes        = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, nullable=False,
                             default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    # One request → one or many allocations (when group is split)
    allocations = db.relationship(
        'Allocation',
        backref='request',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        db.Index('idx_requests_status',    'status'),
        db.Index('idx_requests_submitted', 'submitted_at'),
    )

    def __repr__(self):
        return (f'<ShelterRequest id={self.id} '
                f'size={self.group_size} status={self.status!r}>')

    @property
    def status_label(self):
        """Human-readable status label."""
        return REQUEST_STATUS_LABELS.get(self.status, self.status.title())

    @property
    def status_badge_class(self):
        """CSS badge class for status display."""
        return REQUEST_STATUS_BADGES.get(self.status, 'req-badge-pending')

    @property
    def formatted_time(self):
        """Formatted timestamp for templates."""
        if not self.submitted_at:
            return '—'
        return self.submitted_at.strftime('%d %b %Y, %H:%M UTC')

    @property
    def formatted_date_short(self):
        """Compact date format."""
        if not self.submitted_at:
            return '—'
        return self.submitted_at.strftime('%d %b %H:%M')

    @property
    def has_special_needs(self):
        """True if any vulnerable group count > 0 or special requirements specified."""
        return (
            self.has_injured or self.has_elderly or self.has_disabled or self.has_children or
            self.injured_count > 0 or self.elderly_count > 0 or self.children_count > 0 or
            bool(self.accessibility_requirements) or
            bool(self.medical_requirements) or
            bool(self.other_special_requirements)
        )

    @property
    def special_needs_list(self):
        """List of human-readable special needs tags for badge display."""
        items = []
        if self.injured_count > 0:
            items.append(f"Injured: {self.injured_count}")
        elif self.has_injured:
            items.append("Injured")

        if self.elderly_count > 0:
            items.append(f"Elderly: {self.elderly_count}")
        elif self.has_elderly:
            items.append("Elderly")

        if self.children_count > 0:
            items.append(f"Children: {self.children_count}")
        elif self.has_children:
            items.append("Children")

        if self.accessibility_requirements or self.has_disabled:
            items.append("Accessibility / Wheelchair")

        if self.medical_requirements:
            items.append("Medical Support")

        if self.other_special_requirements:
            items.append("Other Needs")

        return items

    def sync_boolean_flags(self):
        """Synchronize boolean flags with numeric counts and requirement text."""
        self.has_injured = (self.injured_count > 0) or bool(self.medical_requirements)
        self.has_elderly = (self.elderly_count > 0)
        self.has_children = (self.children_count > 0)
        self.has_disabled = bool(self.accessibility_requirements)

    def to_dict(self):
        """Convert request to dictionary."""
        return {
            'id':                          self.id,
            'submitted_by':                self.submitted_by,
            'submitter_name':              self.submitter.full_name if self.submitter else 'Unknown',
            'requesting_team':             self.requesting_team or (self.submitter.full_name if self.submitter else 'Unknown'),
            'contact_phone':               self.contact_phone,
            'group_size':                  self.group_size,
            'latitude':                    float(self.latitude) if self.latitude else 0.0,
            'longitude':                   float(self.longitude) if self.longitude else 0.0,
            'location_name':               self.location_name,
            'injured_count':               self.injured_count,
            'elderly_count':               self.elderly_count,
            'children_count':              self.children_count,
            'accessibility_requirements':  self.accessibility_requirements,
            'medical_requirements':        self.medical_requirements,
            'other_special_requirements':  self.other_special_requirements,
            'status':                      self.status,
            'status_label':                self.status_label,
            'submitted_at':                self.submitted_at.isoformat() if self.submitted_at else None,
            'formatted_time':              self.formatted_time,
            'special_needs':               self.special_needs_list,
        }
