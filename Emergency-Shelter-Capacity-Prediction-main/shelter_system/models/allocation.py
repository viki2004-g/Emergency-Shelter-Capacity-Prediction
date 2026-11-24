"""
models/allocation.py — Allocation model.

An allocation records that a specific number of people from a shelter
request have been directed to a specific shelter.

One request can produce multiple allocations — this happens when
the redistribution engine (Stage 9) splits a large group across
several shelters because no single shelter can safely hold them all.

Example:
  Request #7 (group size 150)
    → Allocation: Shelter B, 50 people
    → Allocation: Shelter C, 60 people
    → Allocation: Shelter D, 40 people

The allocation is not "live" until confirmed=True.
The responder reviews the recommendation and clicks "Confirm Allocation".
Only then is the shelter occupancy updated (inside a database transaction
to prevent two responders over-allocating at the same time).
"""

from datetime import datetime
from extensions import db


class Allocation(db.Model):
    __tablename__ = 'allocations'

    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)

    request_id      = db.Column(
        db.Integer,
        db.ForeignKey('shelter_requests.id', ondelete='RESTRICT'),
        nullable=False
    )
    shelter_id      = db.Column(
        db.Integer,
        db.ForeignKey('shelters.id', ondelete='RESTRICT'),
        nullable=False
    )

    allocated_count = db.Column(db.Integer, nullable=False)

    # confirmed=False → proposed plan, not yet executed
    # confirmed=True  → responder confirmed; occupancy has been updated
    confirmed    = db.Column(db.Boolean, nullable=False, default=False)
    confirmed_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    confirmed_at = db.Column(db.DateTime, nullable=True)

    notes      = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        db.Index('idx_alloc_request', 'request_id'),
        db.Index('idx_alloc_shelter', 'shelter_id'),
        db.Index('idx_alloc_created', 'created_at'),
    )

    def __repr__(self):
        return (f'<Allocation id={self.id} '
                f'request_id={self.request_id} shelter_id={self.shelter_id} '
                f'count={self.allocated_count} confirmed={self.confirmed}>')
