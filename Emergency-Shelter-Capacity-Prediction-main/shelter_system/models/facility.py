"""
models/facility.py — ShelterFacility model.

One row per shelter — records what physical facilities are present.
Boolean flags allow the recommendation engine (Stage 8) to filter
shelters that cannot meet a group's specific requirements.

Facilities tracked:
  medical support, food, wheelchair access, electricity, toilets,
  running water, kitchen, family area
"""

from datetime import datetime
from extensions import db


class ShelterFacility(db.Model):
    __tablename__ = 'shelter_facilities'

    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    shelter_id = db.Column(
        db.Integer,
        db.ForeignKey('shelters.id', ondelete='CASCADE'),
        nullable=False,
        unique=True   # One facility record per shelter
    )

    # ── Facility flags ────────────────────────────────────────────────────────
    has_medical_support   = db.Column(db.Boolean, nullable=False, default=False)
    has_food              = db.Column(db.Boolean, nullable=False, default=False)
    has_wheelchair_access = db.Column(db.Boolean, nullable=False, default=False)
    has_electricity       = db.Column(db.Boolean, nullable=False, default=False)
    has_toilets           = db.Column(db.Boolean, nullable=False, default=False)
    has_running_water     = db.Column(db.Boolean, nullable=False, default=False)
    has_kitchen           = db.Column(db.Boolean, nullable=False, default=False)
    has_family_area       = db.Column(db.Boolean, nullable=False, default=False)

    # Free-text notes — used to describe limitations or special conditions
    notes      = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)
    # Who last updated this record
    updated_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    updater = db.relationship('User', foreign_keys=[updated_by])

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def count_available(self):
        """Number of facility flags that are True."""
        flags = [
            self.has_medical_support, self.has_food, self.has_wheelchair_access,
            self.has_electricity, self.has_toilets, self.has_running_water,
            self.has_kitchen, self.has_family_area,
        ]
        return sum(1 for f in flags if f)

    def to_dict(self):
        """Return facility flags as a plain dict (useful for tests and APIs)."""
        return {
            'has_medical_support':   self.has_medical_support,
            'has_food':              self.has_food,
            'has_wheelchair_access': self.has_wheelchair_access,
            'has_electricity':       self.has_electricity,
            'has_toilets':           self.has_toilets,
            'has_running_water':     self.has_running_water,
            'has_kitchen':           self.has_kitchen,
            'has_family_area':       self.has_family_area,
        }

    def __repr__(self):
        active = [k for k, v in self.to_dict().items() if v]
        return f'<ShelterFacility shelter_id={self.shelter_id} active={active}>'

