"""
services/alerts.py — Emergency Alerts Generation, Deduplication, and Lifecycle Service.

Monitors real-time shelter state and generates actionable warnings for:
  1. Overcrowded shelter (current occupancy > max capacity)
  2. Critical shelter capacity (occupancy >= 95% or safe available capacity <= 0)
  3. Predicted future overload (6-hour predictive arrival rate exceeding limits)
  4. Important resource shortages (depleted water, food portions, medicine kits, or beds)
  5. Facility damage (shelter status marked 'damaged')

Features:
  - Deduplication: Prevents duplicate active alerts for the same (shelter, alert_type).
  - Condition Updates: Updates message & severity if metrics change while alert is active.
  - Auto-Resolution: Clears previous capacity/overload/shortage alerts when conditions recover.
  - Read / Unread tracking: Tracks whether operational personnel have acknowledged an alert.
  - Authority resolution: Records the user and timestamp who resolved the condition.
"""

from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from extensions import db
from models.alert import Alert
from models.shelter import Shelter
from models.resource import Resource
from models.user import User
from services.prediction import predict_shelter_occupancy



def create_or_update_alert(
    shelter_id: Optional[int],
    alert_type: str,
    severity: str,
    message: str,
    auto_commit: bool = False
) -> Tuple[Alert, bool]:
    """
    Create a new alert or update an existing unresolved alert of the same type for this shelter.

    Deduplication Guarantee:
      If an unresolved alert for (shelter_id, alert_type) already exists, it is NOT duplicated.
      Instead, its severity and message are refreshed with the latest telemetry.

    Returns:
      (alert: Alert, is_new: bool)
    """
    existing = Alert.query.filter_by(
        shelter_id=shelter_id,
        alert_type=alert_type,
        is_resolved=False
    ).first()

    if existing:
        # Update metrics if changed or escalated
        changed = False
        if existing.severity != severity:
            existing.severity = severity
            changed = True
        if existing.message != message:
            existing.message = message
            changed = True

        if auto_commit and changed:
            db.session.commit()
        return existing, False

    # Create new alert
    alert = Alert(
        shelter_id=shelter_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        is_read=False,
        is_resolved=False,
        created_at=datetime.utcnow()
    )
    db.session.add(alert)
    if auto_commit:
        db.session.commit()

    return alert, True


def auto_resolve_alert(
    shelter_id: Optional[int],
    alert_type: str,
    auto_commit: bool = False
) -> Optional[Alert]:
    """
    Automatically resolve an active alert when conditions return to safe operational limits.
    """
    existing = Alert.query.filter_by(
        shelter_id=shelter_id,
        alert_type=alert_type,
        is_resolved=False
    ).first()

    if existing:
        existing.is_resolved = True
        existing.resolved_at = datetime.utcnow()
        if auto_commit:
            db.session.commit()
        return existing

    return None


def evaluate_shelter_alerts(shelter: Shelter, auto_commit: bool = False) -> Dict[str, Any]:
    """
    Evaluate all operational rules against a single shelter.
    Generates, updates, or auto-resolves alerts for:
      - Overcrowding (>100% capacity)
      - Critical capacity (>=95% or safe headroom <= 0, or warning if >= safe_limit)
      - Forecast overload (6-hour linear prediction)
      - Resource shortages (depleted water, food, medicine, beds)
      - Facility damage (status == 'damaged')
    """
    created_count = 0
    updated_count = 0
    resolved_count = 0

    # ── 1. Overcrowding Condition ──────────────────────────────────────────────
    if shelter.current_occupancy > shelter.max_capacity:
        excess = shelter.current_occupancy - shelter.max_capacity
        msg = (
            f"Shelter '{shelter.name}' is OVERCROWDED: {shelter.current_occupancy}/{shelter.max_capacity} "
            f"beds occupied ({shelter.occupancy_pct}%). Exceeds physical capacity by {excess} people. "
            f"Immediate evacuee redistribution required."
        )
        _, is_new = create_or_update_alert(shelter.id, 'overcrowded', 'critical', msg)
        if is_new:
            created_count += 1
        else:
            updated_count += 1
    else:
        resolved = auto_resolve_alert(shelter.id, 'overcrowded')
        if resolved:
            resolved_count += 1

    # ── 2. Critical Capacity Condition ─────────────────────────────────────────
    # If already overcrowded, overcrowding alert is primary; otherwise check critical/warning
    if shelter.current_occupancy <= shelter.max_capacity:
        if shelter.occupancy_pct >= 95.0 or shelter.safe_available_capacity <= 0 or shelter.status == 'full':
            deficit = abs(min(0, shelter.safe_available_capacity))
            msg = (
                f"Shelter '{shelter.name}' is at CRITICAL capacity: {shelter.current_occupancy}/{shelter.max_capacity} "
                f"beds occupied ({shelter.occupancy_pct}%). Safe planning headroom breached "
                f"({deficit} evacuees over safe buffer limit)."
            )
            _, is_new = create_or_update_alert(shelter.id, 'critical_capacity', 'critical', msg)
            if is_new:
                created_count += 1
            else:
                updated_count += 1
        elif shelter.occupancy_pct >= 80.0 or shelter.safe_available_capacity <= max(1, int(0.15 * shelter.safe_capacity)):
            msg = (
                f"Shelter '{shelter.name}' approaching safe capacity threshold: "
                f"{shelter.current_occupancy}/{shelter.safe_capacity} safe beds occupied ({shelter.occupancy_pct}%). "
                f"Headroom remaining: {shelter.safe_available_capacity} spaces."
            )
            _, is_new = create_or_update_alert(shelter.id, 'critical_capacity', 'warning', msg)
            if is_new:
                created_count += 1
            else:
                updated_count += 1
        else:
            # Capacity is safe and headroom > 0
            resolved = auto_resolve_alert(shelter.id, 'critical_capacity')
            if resolved:
                resolved_count += 1


    # ── 3. Predicted Future Overload ──────────────────────────────────────────
    if shelter.status == 'active':
        try:
            pred = predict_shelter_occupancy(shelter, hours_ahead=6)
            if pred.get('has_prediction'):

                rate = pred.get('arrival_rate_per_hour', 0.0)
                pred_occ = pred.get('predicted_occupancy', shelter.current_occupancy)
                pred_pct = pred.get('predicted_pct', shelter.occupancy_pct)

                if pred_occ > shelter.max_capacity and rate > 0:
                    msg = (
                        f"Forecast Overload: Shelter '{shelter.name}' is projected to exceed physical capacity "
                        f"({pred_occ}/{shelter.max_capacity} beds, {pred_pct}%) within 6 hours based on current "
                        f"inbound rate (+{rate}/hr)."
                    )
                    _, is_new = create_or_update_alert(shelter.id, 'predicted_overload', 'critical', msg)
                    if is_new:
                        created_count += 1
                    else:
                        updated_count += 1
                elif pred_occ > shelter.safe_capacity and rate > 0:
                    msg = (
                        f"Forecast Warning: Shelter '{shelter.name}' is projected to exceed safe planning capacity "
                        f"({pred_occ}/{shelter.safe_capacity} beds, {pred_pct}%) within 6 hours (+{rate}/hr)."
                    )
                    _, is_new = create_or_update_alert(shelter.id, 'predicted_overload', 'warning', msg)
                    if is_new:
                        created_count += 1
                    else:
                        updated_count += 1
                else:
                    resolved = auto_resolve_alert(shelter.id, 'predicted_overload')
                    if resolved:
                        resolved_count += 1
        except Exception:
            # Prediction failure should never disrupt main alert scanning
            pass

    # ── 4. Important Resource Shortage ─────────────────────────────────────────
    res = getattr(shelter, 'resource', None)
    if res and shelter.status == 'active':
        depleted_critical = []
        depleted_warning = []

        # Water: < 2L per sheltered person or 0
        min_water = shelter.current_occupancy * 2
        if res.water_litres <= 0 and shelter.current_occupancy > 0:
            depleted_critical.append("Zero Drinking Water")
        elif res.water_litres < min_water and shelter.current_occupancy > 0:
            depleted_warning.append(f"Drinking water reserves low ({res.water_litres}L)")

        # Food: < 1 portion per person or 0
        min_food = shelter.current_occupancy
        if res.food_portions <= 0 and shelter.current_occupancy > 0:
            depleted_critical.append("Zero Food Portions")
        elif res.food_portions < min_food and shelter.current_occupancy > 0:
            depleted_warning.append(f"Food reserves low ({res.food_portions} portions)")

        # Medical kits: 0 with occupants
        if res.medicine_kits <= 0 and shelter.current_occupancy > 0:
            depleted_warning.append("Zero First-Aid/Medicine Kits")

        # Beds available: 0 when occupancy >= safe limit
        if res.beds_available <= 0 and shelter.current_occupancy >= shelter.safe_capacity:
            depleted_warning.append("Zero Unassigned Beds")

        if depleted_critical:
            details = ", ".join(depleted_critical + depleted_warning)
            msg = (
                f"Critical Supply Deficit: Shelter '{shelter.name}' has exhausted essential survival supplies: "
                f"{details}. Immediate replenishment or evacuee transfer required."
            )
            _, is_new = create_or_update_alert(shelter.id, 'resource_shortage', 'critical', msg)
            if is_new:
                created_count += 1
            else:
                updated_count += 1
        elif depleted_warning:
            details = ", ".join(depleted_warning)
            msg = (
                f"Supply Warning: Shelter '{shelter.name}' has low inventory reserves: "
                f"{details}. Restock request recommended."
            )
            _, is_new = create_or_update_alert(shelter.id, 'resource_shortage', 'warning', msg)
            if is_new:
                created_count += 1
            else:
                updated_count += 1
        else:
            resolved = auto_resolve_alert(shelter.id, 'resource_shortage')
            if resolved:
                resolved_count += 1

    # ── 5. Facility Hazard / Damage ────────────────────────────────────────────
    if shelter.status == 'damaged':
        msg = (
            f"Facility Hazard: Shelter '{shelter.name}' has been marked DAMAGED and structurally unsafe. "
            f"Must NOT accept evacuees. Immediate inspection required."
        )
        _, is_new = create_or_update_alert(shelter.id, 'shelter_damaged', 'critical', msg)
        if is_new:
            created_count += 1
        else:
            updated_count += 1
    else:
        resolved = auto_resolve_alert(shelter.id, 'shelter_damaged')
        if resolved:
            resolved_count += 1

    if auto_commit:
        db.session.commit()

    return {
        'created': created_count,
        'updated': updated_count,
        'resolved': resolved_count,
    }


def evaluate_all_alerts(commit: bool = True) -> Dict[str, Any]:
    """
    System-wide scan across all shelters to detect, update, and auto-resolve alerts.
    """
    shelters = Shelter.query.all()
    total_created = 0
    total_updated = 0
    total_resolved = 0

    for s in shelters:
        res = evaluate_shelter_alerts(s, auto_commit=False)
        total_created += res['created']
        total_updated += res['updated']
        total_resolved += res['resolved']

    if commit:
        db.session.commit()

    return {
        'shelters_scanned': len(shelters),
        'created': total_created,
        'updated': total_updated,
        'resolved': total_resolved,
    }


def mark_alert_read(alert_id: int, user: Optional[User] = None) -> Optional[Alert]:
    """Mark an individual alert as read."""
    alert = db.session.get(Alert, alert_id)
    if alert and not alert.is_read:
        alert.is_read = True
        db.session.commit()
    return alert


def mark_all_alerts_read(user: Optional[User] = None) -> int:
    """Mark all unresolved alerts as read."""
    unread_alerts = Alert.query.filter_by(is_read=False, is_resolved=False).all()
    for a in unread_alerts:
        a.is_read = True
    db.session.commit()
    return len(unread_alerts)


def resolve_alert(
    alert_id: int,
    user: User,
    notes: Optional[str] = None
) -> Optional[Alert]:
    """
    Resolve an active alert. Restricted to Authority and Admin roles.
    """
    alert = db.session.get(Alert, alert_id)
    if not alert:
        return None

    alert.is_resolved = True
    alert.resolved_by = user.id
    alert.resolved_at = datetime.utcnow()
    alert.is_read = True

    if notes:
        alert.message = f"{alert.message} [Resolved Note: {notes}]"

    db.session.commit()
    return alert


def get_alert_counts() -> Dict[str, int]:
    """Return high-level summary counters for badges and top bars."""
    unresolved_q = Alert.query.filter_by(is_resolved=False)
    total_unresolved = unresolved_q.count()
    critical_count = unresolved_q.filter_by(severity='critical').count()
    warning_count = unresolved_q.filter_by(severity='warning').count()
    unread_count = unresolved_q.filter_by(is_read=False).count()

    return {
        'total_unresolved': total_unresolved,
        'critical': critical_count,
        'warning': warning_count,
        'unread': unread_count,
    }


def get_active_alerts(
    limit: Optional[int] = None,
    shelter_id: Optional[int] = None,
    severity: Optional[str] = None
) -> List[Alert]:
    """Query active (unresolved) alerts with optional filtering."""
    q = Alert.query.filter_by(is_resolved=False)

    if shelter_id:
        q = q.filter_by(shelter_id=shelter_id)
    if severity:
        q = q.filter_by(severity=severity)

    # Sort critical first, then newest
    q = q.order_by(
        db.case((Alert.severity == 'critical', 1), (Alert.severity == 'warning', 2), else_=3),
        Alert.created_at.desc(),
        Alert.id.desc()
    )

    if limit:
        q = q.limit(limit)

    return q.all()
