"""
models/resource.py — Resource model.

One row per shelter — tracks consumable supply quantities.
Updated by shelter managers when supplies arrive or are consumed.

Quantities:
  beds_available  — sleeping spaces currently free (not beds in the shelter)
  food_portions   — meal portions currently in stock
  water_litres    — litres of safe drinking water available
  medicine_kits   — basic first-aid / medicine kits
  blankets        — blankets or sleeping bags

Low-resource thresholds (used by the alert system in Stage 11):
  food_portions < 50    → low food alert
  water_litres  < 200   → low water alert
  medicine_kits < 5     → low medicine alert

These quantities also feed into the recommendation scoring engine (Stage 8).
"""

from datetime import datetime
from extensions import db


# Thresholds below which a resource is considered "low"
LOW_THRESHOLDS = {
    'food_portions': 50,
    'water_litres':  200,
    'medicine_kits': 5,
    'blankets':      20,
    'beds_available': 0,   # any value above 0 is OK
}


class Resource(db.Model):
    __tablename__ = 'resources'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    shelter_id = db.Column(
        db.Integer,
        db.ForeignKey('shelters.id', ondelete='CASCADE'),
        nullable=False,
        unique=True   # One resource record per shelter
    )

    # ── Consumable quantities (all non-negative integers) ─────────────────────
    beds_available = db.Column(db.Integer, nullable=False, default=0)
    food_portions  = db.Column(db.Integer, nullable=False, default=0)
    water_litres   = db.Column(db.Integer, nullable=False, default=0)
    medicine_kits  = db.Column(db.Integer, nullable=False, default=0)
    blankets       = db.Column(db.Integer, nullable=False, default=0)

    # Free-text notes about supply status or incoming deliveries
    notes      = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)

    # Who last updated the record
    updated_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    updater = db.relationship('User', foreign_keys=[updated_by])

    # ── Helpers ───────────────────────────────────────────────────────────────

    def is_low(self, field):
        """True if the given field quantity is at or below its low threshold."""
        threshold = LOW_THRESHOLDS.get(field, 0)
        return getattr(self, field, 0) <= threshold

    @property
    def any_low(self):
        """True if any resource quantity is at a low level."""
        return any(self.is_low(f) for f in LOW_THRESHOLDS)

    @property
    def low_fields(self):
        """List of field names that are below their low threshold."""
        return [f for f in LOW_THRESHOLDS if self.is_low(f)]

    def to_dict(self):
        """Return resource quantities as a plain dict."""
        return {
            'beds_available': self.beds_available,
            'food_portions':  self.food_portions,
            'water_litres':   self.water_litres,
            'medicine_kits':  self.medicine_kits,
            'blankets':       self.blankets,
        }

    def __repr__(self):
        return (f'<Resource shelter_id={self.shelter_id} '
                f'beds={self.beds_available} food={self.food_portions} '
                f'water={self.water_litres}L>')
