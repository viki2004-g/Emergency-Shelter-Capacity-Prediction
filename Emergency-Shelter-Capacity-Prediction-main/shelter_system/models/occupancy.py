"""
models/occupancy.py — OccupancyHistory model.

Every time a shelter manager updates the occupancy count, a row is inserted
here. This table is append-only — records are never updated or deleted.

Why do we need this?
  The prediction engine (Stage 10) reads this history to calculate
  how quickly people are arriving at each shelter, then forecasts
  future occupancy: "Shelter B may reach capacity in ~4 hours".

  It also powers the occupancy trend charts on the dashboard (Stage 11).
"""

from datetime import datetime
from extensions import db


class OccupancyHistory(db.Model):
    __tablename__ = 'occupancy_history'

    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    shelter_id  = db.Column(
        db.Integer,
        db.ForeignKey('shelters.id', ondelete='CASCADE'),
        nullable=False
    )
    occupancy   = db.Column(db.Integer, nullable=False)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Who recorded this update (shelter manager / responder / system)
    recorded_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    # Prediction queries always filter by shelter_id and order by recorded_at
    __table_args__ = (
        db.Index('idx_history_shelter_time', 'shelter_id', 'recorded_at'),
    )

    @property
    def formatted_time(self):
        """Format timestamp for UI tables."""
        if not self.recorded_at:
            return '—'
        return self.recorded_at.strftime('%Y-%m-%d %H:%M:%S UTC')

    @property
    def short_time(self):
        """Format timestamp for compact badges."""
        if not self.recorded_at:
            return '—'
        return self.recorded_at.strftime('%d %b %H:%M')

    @property
    def occupancy_pct(self):
        """Calculate occupancy percentage relative to shelter's max capacity."""
        if self.shelter and self.shelter.max_capacity > 0:
            from services.capacity import calculate_occupancy_percentage
            return calculate_occupancy_percentage(self.occupancy, self.shelter.max_capacity)
        return 0.0

    @property
    def available_capacity(self):
        """Calculate available capacity relative to shelter's max capacity."""
        if self.shelter:
            from services.capacity import calculate_available_capacity
            return calculate_available_capacity(self.shelter.max_capacity, self.occupancy)
        return 0

    @property
    def safe_available_capacity(self):
        """Calculate safe available capacity relative to shelter's safe capacity."""
        if self.shelter:
            from services.capacity import calculate_safe_available_capacity
            return calculate_safe_available_capacity(
                self.shelter.max_capacity,
                self.occupancy,
                self.shelter.safe_limit
            )
        return 0

    @property
    def capacity_status(self):
        """Determine status at this snapshot."""
        from services.capacity import determine_occupancy_status
        return determine_occupancy_status(self.occupancy_pct)

    def to_dict(self):
        return {
            'id':                      self.id,
            'shelter_id':              self.shelter_id,
            'occupancy':               self.occupancy,
            'recorded_at':             self.recorded_at.isoformat() if self.recorded_at else None,
            'recorded_by':             self.recorded_by,
            'recorder_name':           self.recorder.full_name if self.recorder else 'System',
            'occupancy_pct':           self.occupancy_pct,
            'available_capacity':      self.available_capacity,
            'safe_available_capacity': self.safe_available_capacity,
            'capacity_status':         self.capacity_status,
        }

    def __repr__(self):
        return (f'<OccupancyHistory shelter_id={self.shelter_id} '
                f'occupancy={self.occupancy} at={self.recorded_at}>')
