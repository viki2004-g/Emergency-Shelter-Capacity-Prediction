"""
services/capacity.py — Capacity calculations, configurable occupancy thresholds,
and occupancy history management.

Core formulas:
  Available Capacity      = Maximum Capacity - Current Occupancy
  Occupancy Percentage    = (Current Occupancy / Maximum Capacity) * 100
  Safe Planning Capacity  = Maximum Capacity * (Safe Limit % / 100)
  Safe Available Capacity = Safe Planning Capacity - Current Occupancy

Configurable status thresholds:
  0  – 60%  -> Safe
  61 – 80%  -> Moderate
  81 – 95%  -> High
  96 – 100% -> Critical
  Above 100%-> Overcrowded
"""

from datetime import datetime
from extensions import db
from models.occupancy import OccupancyHistory


# Fallback defaults in case config is not loaded
DEFAULT_SAFE_LIMIT_PCT = 85

DEFAULT_THRESHOLDS = {
    'safe':        60.0,
    'moderate':    80.0,
    'high':        95.0,
    'critical':    100.0,
}

STATUS_LABELS = {
    'safe':        'Safe',
    'moderate':    'Moderate',
    'high':        'High',
    'critical':    'Critical',
    'overcrowded': 'Overcrowded',
}

STATUS_BADGE_CLASSES = {
    'safe':        'cap-badge-safe',
    'moderate':    'cap-badge-moderate',
    'high':        'cap-badge-high',
    'critical':    'cap-badge-critical',
    'overcrowded': 'cap-badge-overcrowded',
}


def get_configured_safe_limit_pct() -> int:
    """Get the global safe occupancy limit percentage from Flask config or fallback."""
    try:
        from flask import current_app
        if current_app and 'SAFE_OCCUPANCY_LIMIT_PCT' in current_app.config:
            return int(current_app.config['SAFE_OCCUPANCY_LIMIT_PCT'])
    except Exception:
        pass
    return DEFAULT_SAFE_LIMIT_PCT


def get_configured_thresholds() -> dict:
    """
    Get configurable occupancy thresholds from Flask config or fallback.
    Returns:
      {'safe': float, 'moderate': float, 'high': float, 'critical': float}
    """
    try:
        from flask import current_app
        if current_app and 'OCCUPANCY_THRESHOLDS' in current_app.config:
            return current_app.config['OCCUPANCY_THRESHOLDS']
    except Exception:
        pass
    return DEFAULT_THRESHOLDS.copy()


def calculate_available_capacity(max_capacity: int, current_occupancy: int) -> int:
    """
    Available Capacity = Maximum Capacity - Current Occupancy.
    Can be negative if current occupancy exceeds maximum capacity.
    """
    max_cap = int(max_capacity or 0)
    curr_occ = int(current_occupancy or 0)
    return max_cap - curr_occ


def calculate_occupancy_percentage(current_occupancy: int, max_capacity: int) -> float:
    """
    Occupancy Percentage = (Current Occupancy / Maximum Capacity) * 100.
    Returns 0.0 if max_capacity <= 0. Rounded to 1 decimal place.
    """
    max_cap = int(max_capacity or 0)
    curr_occ = int(current_occupancy or 0)
    if max_cap <= 0:
        return 0.0
    return round((curr_occ / max_cap) * 100.0, 1)


def calculate_safe_capacity(max_capacity: int, safe_limit_pct: float = None) -> int:
    """
    Safe Planning Capacity = Maximum Capacity * (Safe Limit % / 100).
    Uses shelter's safe_limit_pct override if provided, otherwise global config.
    """
    max_cap = int(max_capacity or 0)
    if safe_limit_pct is None or safe_limit_pct <= 0:
        safe_limit_pct = get_configured_safe_limit_pct()
    return int(max_cap * (float(safe_limit_pct) / 100.0))


def calculate_safe_available_capacity(max_capacity: int, current_occupancy: int,
                                      safe_limit_pct: float = None) -> int:
    """
    Safe Available Capacity = Safe Planning Capacity - Current Occupancy.
    Can be negative if current occupancy has exceeded the safe planning limit.
    """
    curr_occ = int(current_occupancy or 0)
    safe_cap = calculate_safe_capacity(max_capacity, safe_limit_pct)
    return safe_cap - curr_occ


def determine_occupancy_status(occupancy_pct: float, thresholds: dict = None) -> str:
    """
    Determine occupancy status using configurable thresholds:
      0  - 60%  -> 'safe'
      61 - 80%  -> 'moderate'
      81 - 95%  -> 'high'
      96 - 100% -> 'critical'
      Above 100%-> 'overcrowded'
    """
    if thresholds is None:
        thresholds = get_configured_thresholds()

    safe_t = float(thresholds.get('safe', 60.0))
    mod_t  = float(thresholds.get('moderate', 80.0))
    high_t = float(thresholds.get('high', 95.0))
    crit_t = float(thresholds.get('critical', 100.0))

    if occupancy_pct > crit_t:
        return 'overcrowded'
    elif occupancy_pct > high_t:
        return 'critical'
    elif occupancy_pct > mod_t:
        return 'high'
    elif occupancy_pct > safe_t:
        return 'moderate'
    else:
        return 'safe'


def get_status_label(status: str) -> str:
    """Human-readable display name for occupancy status."""
    return STATUS_LABELS.get(status, status.title() if status else '—')


def get_status_badge_class(status: str) -> str:
    """CSS class for styling the occupancy badge."""
    return STATUS_BADGE_CLASSES.get(status, 'cap-badge-safe')


def get_shelter_capacity_metrics(shelter) -> dict:
    """
    Calculates and returns a comprehensive dictionary of all occupancy
    and capacity metrics for a given shelter model instance.
    """
    max_cap   = shelter.max_capacity
    curr_occ  = shelter.current_occupancy
    safe_pct  = shelter.safe_limit_pct if shelter.safe_limit_pct else get_configured_safe_limit_pct()

    avail_cap      = calculate_available_capacity(max_cap, curr_occ)
    occ_pct        = calculate_occupancy_percentage(curr_occ, max_cap)
    safe_cap       = calculate_safe_capacity(max_cap, safe_pct)
    safe_avail_cap = calculate_safe_available_capacity(max_cap, curr_occ, safe_pct)
    status         = determine_occupancy_status(occ_pct)
    status_label   = get_status_label(status)
    badge_class    = get_status_badge_class(status)

    return {
        'max_capacity':           max_cap,
        'current_occupancy':      curr_occ,
        'available_capacity':     avail_cap,
        'occupancy_pct':          occ_pct,
        'safe_limit_pct':         safe_pct,
        'safe_capacity':          safe_cap,
        'safe_available_capacity':safe_avail_cap,
        'status':                 status,
        'status_label':           status_label,
        'badge_class':            badge_class,
    }


def record_occupancy_change(shelter, new_occupancy: int, user_id: int = None,
                            force: bool = False) -> tuple[bool, OccupancyHistory or None]:
    """
    Updates a shelter's current occupancy and creates an immutable OccupancyHistory record.
    Ensures history is never overwritten.

    Args:
        shelter: The Shelter model instance.
        new_occupancy: The new non-negative integer occupancy count.
        user_id: ID of the user performing the change (or None for system).
        force: If True, creates a history record even if new_occupancy == current_occupancy.

    Returns:
        (changed: bool, history_entry: OccupancyHistory or None)
    """
    if new_occupancy < 0:
        raise ValueError("Occupancy cannot be negative.")

    old_occupancy = shelter.current_occupancy
    changed = (new_occupancy != old_occupancy)

    if not changed and not force:
        return False, None

    shelter.current_occupancy = new_occupancy
    shelter.updated_at = datetime.utcnow()

    history_entry = OccupancyHistory(
        shelter_id=shelter.id,
        occupancy=new_occupancy,
        recorded_by=user_id,
        recorded_at=datetime.utcnow()
    )
    db.session.add(history_entry)
    db.session.commit()

    return True, history_entry
