"""
models/alert.py — Alert model.

Alerts are system-generated warnings that appear on the dashboard
(Stage 11). They are created automatically when:

  overcrowded         — shelter.current_occupancy > shelter.max_capacity
  critical_capacity   — occupancy >= 96% of max capacity
  predicted_overload  — prediction engine forecasts overload within N hours
  resource_shortage   — beds / food / water below a minimum threshold
  shelter_damaged     — shelter status changed to 'damaged'

Alerts can be system-wide (shelter_id = NULL) or shelter-specific.

Authorized users (authority, admin) can mark an alert as resolved
after the situation is addressed.
"""

from datetime import datetime
from extensions import db


class Alert(db.Model):
    __tablename__ = 'alerts'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # NULL shelter_id → system-wide alert not tied to one shelter
    shelter_id = db.Column(
        db.Integer,
        db.ForeignKey('shelters.id', ondelete='CASCADE'),
        nullable=True
    )

    alert_type = db.Column(
        db.Enum('overcrowded', 'critical_capacity', 'predicted_overload',
                'resource_shortage', 'shelter_damaged',
                name='alert_type'),
        nullable=False
    )

    severity = db.Column(
        db.Enum('info', 'warning', 'critical', name='alert_severity'),
        nullable=False,
        default='warning'
    )

    message     = db.Column(db.Text, nullable=False)
    is_read     = db.Column(db.Boolean, nullable=False, default=False)
    is_resolved = db.Column(db.Boolean, nullable=False, default=False)

    resolved_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationship to the user who resolved the alert
    resolver = db.relationship('User', foreign_keys=[resolved_by])

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Dashboard queries: unresolved alerts ordered by date
        db.Index('idx_alerts_unresolved', 'is_resolved', 'created_at'),
        db.Index('idx_alerts_shelter',    'shelter_id'),
    )

    @property
    def severity_badge_class(self):
        if self.severity == 'critical':
            return 'bg-danger text-white'
        elif self.severity == 'warning':
            return 'bg-warning text-dark'
        return 'bg-info text-dark'

    @property
    def severity_pill_class(self):
        if self.severity == 'critical':
            return 'pill-critical'
        elif self.severity == 'warning':
            return 'pill-high'
        return 'pill-moderate'

    @property
    def severity_icon(self):
        if self.severity == 'critical':
            return 'bi-exclamation-octagon-fill'
        elif self.severity == 'warning':
            return 'bi-exclamation-triangle-fill'
        return 'bi-info-circle-fill'

    @property
    def type_label(self):
        labels = {
            'overcrowded':         'Overcrowded Shelter',
            'critical_capacity':   'Critical Capacity',
            'predicted_overload':  'Forecast Overload Risk',
            'resource_shortage':   'Resource Shortage',
            'shelter_damaged':     'Facility Hazard / Damaged',
        }
        return labels.get(self.alert_type, self.alert_type.replace('_', ' ').title())

    @property
    def time_ago(self):
        """Format a human-readable relative timestamp."""
        if not self.created_at:
            return 'Just now'
        delta = datetime.utcnow() - self.created_at
        seconds = max(0, int(delta.total_seconds()))
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 7:
            return f"{days}d ago"
        return self.created_at.strftime('%d %b %H:%M')

    def __repr__(self):
        return (f'<Alert id={self.id} type={self.alert_type!r} '
                f'severity={self.severity!r} resolved={self.is_resolved} read={self.is_read}>')

