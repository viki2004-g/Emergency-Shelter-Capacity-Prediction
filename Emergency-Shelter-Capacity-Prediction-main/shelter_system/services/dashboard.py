"""
services/dashboard.py — Main Emergency Management Dashboard Service.

Aggregates real-time operational data directly from MySQL tables:
  - Total network shelters (active, inactive, closed)
  - Total physical capacity, safe planning capacity, current occupancy, safe available headroom
  - Critical capacity shelters (occupancy >= 95% or safe limit exceeded)
  - Overcrowded shelters (current occupancy > max capacity)
  - Predicted overload forecasts (from prediction heuristic engine)
  - Resource shortages (depleted beds, food portions, water litres, medicine kits)
  - Unresolved emergency alerts from the alerts table
  - Recent confirmed allocations and recent incoming shelter requests
  - High-utility, purposeful Chart.js payloads for situational awareness
  - Role-aware context filters (admin/authority vs shelter manager vs responder vs citizen)
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from extensions import db
from models.alert import Alert
from models.allocation import Allocation
from models.occupancy import OccupancyHistory
from models.request import ShelterRequest
from models.resource import Resource
from models.shelter import Shelter
from models.user import User
from services.prediction import predict_shelter_occupancy


def get_dashboard_summary(
    user: Optional[User] = None,
    hours_ahead: int = 6
) -> Dict[str, Any]:
    """
    Computes a comprehensive situational awareness dictionary for the main EOC dashboard.

    Args:
        user:        The currently logged-in User instance (or None for anonymous/public).
        hours_ahead: Forecast window in hours for predicted load evaluation (default 6).

    Returns:
        Dict containing real database counts, shelter lists, alert items, recent feeds,
        and JSON-serializable chart data structures.
    """
    # ── 1. Query All Shelters & Join Relational Context ───────────────────────
    all_shelters: List[Shelter] = Shelter.query.order_by(Shelter.name.asc()).all()
    active_shelters: List[Shelter] = [s for s in all_shelters if s.status == 'active']
    inactive_shelters: List[Shelter] = [s for s in all_shelters if s.status != 'active']

    # ── 2. Calculate Core Network Capacity Metrics ─────────────────────────────
    total_shelters = len(all_shelters)
    active_count = len(active_shelters)
    inactive_count = len(inactive_shelters)

    total_capacity = sum(s.max_capacity for s in active_shelters)
    total_occupancy = sum(s.current_occupancy for s in active_shelters)
    total_safe_capacity = sum(s.safe_capacity for s in active_shelters)

    global_occupancy_pct = (
        round((total_occupancy / total_capacity) * 100, 1) if total_capacity > 0 else 0.0
    )

    # Net available headroom across all active facilities
    net_safe_available = sum(s.safe_available_capacity for s in active_shelters)
    usable_safe_available = sum(max(0, s.safe_available_capacity) for s in active_shelters)
    total_safe_deficit = sum(abs(min(0, s.safe_available_capacity)) for s in active_shelters)

    # Global status designation based on aggregate load
    if global_occupancy_pct >= 95.0 or total_safe_deficit > 100:
        global_network_status = 'critical'
        global_status_label = 'CRITICAL SURGE'
    elif global_occupancy_pct >= 85.0 or total_safe_deficit > 0:
        global_network_status = 'high'
        global_status_label = 'ELEVATED LOAD'
    elif global_occupancy_pct >= 60.0:
        global_network_status = 'moderate'
        global_status_label = 'MODERATE'
    else:
        global_network_status = 'safe'
        global_status_label = 'NORMAL'

    # ── 3. Evaluate Status Categories & Predict Overloads ─────────────────────
    critical_shelters: List[Dict[str, Any]] = []
    overcrowded_shelters: List[Dict[str, Any]] = []
    predicted_overloads: List[Dict[str, Any]] = []
    resource_shortages: List[Dict[str, Any]] = []
    shelter_cards_data: List[Dict[str, Any]] = []

    for s in all_shelters:
        # Evaluate 6-hour prediction
        pred = predict_shelter_occupancy(s, hours_ahead=hours_ahead)

        # Check resource depletion
        res = getattr(s, 'resource', None)
        has_shortage = bool(res and res.any_low)
        shortage_fields = res.low_fields if res else []

        # Triage status flags
        is_overcrowded = (s.current_occupancy > s.max_capacity)
        # Critical if physically overcrowded, >= 95% occupancy, or safe headroom breached
        is_critical = (
            is_overcrowded or
            s.occupancy_pct >= 95.0 or
            s.safe_available_capacity <= 0 or
            s.status in ('full', 'damaged')
        )

        item_data = {
            'shelter':                 s,
            'id':                      s.id,
            'name':                    s.name,
            'address':                 s.address,
            'status':                  s.status,
            'is_operational':          s.is_operational,
            'current_occupancy':       s.current_occupancy,
            'max_capacity':            s.max_capacity,
            'safe_capacity':           s.safe_capacity,
            'safe_limit_pct':          s.safe_limit,
            'safe_available_capacity': s.safe_available_capacity,
            'occupancy_pct':           s.occupancy_pct,
            'capacity_status':         s.capacity_status,
            'capacity_badge_class':    s.capacity_badge_class,
            'prediction':              pred,
            'has_shortage':            has_shortage,
            'shortage_fields':         shortage_fields,
            'facility':                getattr(s, 'facility', None),
            'resource':                res,
            'managed_by':              s.managed_by,
        }

        shelter_cards_data.append(item_data)

        if is_overcrowded:
            overcrowded_shelters.append(item_data)

        if is_critical:
            critical_shelters.append(item_data)

        if pred.get('overload_risk') in ('high', 'critical'):
            predicted_overloads.append(item_data)

        if has_shortage:
            resource_shortages.append(item_data)

    # ── 4. Query Unresolved Emergency Alerts ──────────────────────────────────
    from services.alerts import evaluate_all_alerts, get_alert_counts
    try:
        evaluate_all_alerts(commit=True)
    except Exception:
        pass

    unresolved_alerts: List[Alert] = (
        Alert.query
        .filter_by(is_resolved=False)
        .order_by(
            db.case((Alert.severity == 'critical', 1), (Alert.severity == 'warning', 2), else_=3),
            Alert.created_at.desc(),
            Alert.id.desc()
        )
        .limit(10)
        .all()
    )
    alert_counts = get_alert_counts()


    # ── 5. Query Recent Confirmed Allocations ─────────────────────────────────
    recent_allocations: List[Allocation] = (
        Allocation.query
        .filter_by(confirmed=True)
        .order_by(Allocation.confirmed_at.desc(), Allocation.id.desc())
        .limit(10)
        .all()
    )

    # ── 6. Query Recent Incoming Shelter Requests ─────────────────────────────
    recent_requests: List[ShelterRequest] = (
        ShelterRequest.query
        .order_by(ShelterRequest.submitted_at.desc(), ShelterRequest.id.desc())
        .limit(10)
        .all()
    )

    pending_requests_count = (
        ShelterRequest.query
        .filter(ShelterRequest.status.in_(['pending', 'partially_allocated']))
        .count()
    )

    unallocated_people_count = sum(
        r.group_size for r in
        ShelterRequest.query.filter_by(status='pending').all()
    )

    # ── 7. Build Chart.js Datasets (Structured & JSON-Serializable) ───────────
    # Chart 1: Active Shelter Occupancy vs Safe Planning Capacity vs Max Capacity
    active_sorted = sorted(
        [item for item in shelter_cards_data if item['is_operational']],
        key=lambda x: -x['occupancy_pct']
    )

    bar_labels = [item['name'] for item in active_sorted]
    bar_occupancies = [item['current_occupancy'] for item in active_sorted]
    bar_safe_caps = [item['safe_capacity'] for item in active_sorted]
    bar_max_caps = [item['max_capacity'] for item in active_sorted]

    # Color code bars according to capacity status
    bar_colors = []
    for item in active_sorted:
        pct = item['occupancy_pct']
        if pct > 100.0:
            bar_colors.append('#7f1d1d')  # Dark crimson for overcrowded
        elif pct >= 95.0 or item['safe_available_capacity'] <= 0:
            bar_colors.append('#dc2626')  # Critical red
        elif pct >= 80.0:
            bar_colors.append('#f59e0b')  # Amber warning
        elif pct >= 60.0:
            bar_colors.append('#eab308')  # Yellow moderate
        else:
            bar_colors.append('#16a34a')  # Green safe

    chart_shelter_load = {
        'labels':           bar_labels,
        'occupancies':      bar_occupancies,
        'safe_capacities':  bar_safe_caps,
        'max_capacities':   bar_max_caps,
        'bar_colors':       bar_colors,
    }

    # Chart 2: Network Capacity Utilization Breakdown (Doughnut)
    # Ensure segments represent non-overlapping slices that never sum beyond total capacity
    doughnut_occupied = total_occupancy
    doughnut_safe_avail = max(0, min(usable_safe_available, total_safe_capacity - total_occupancy))
    surge_planning_margin = max(0, total_capacity - max(total_occupancy, total_safe_capacity))

    chart_capacity_doughnut = {
        'labels':   ['Current Occupancy', 'Safe Available Headroom', 'Surge Planning Buffer'],
        'data':     [doughnut_occupied, doughnut_safe_avail, surge_planning_margin],
        'colors':   [
            '#dc2626' if global_occupancy_pct >= 90 else ('#f59e0b' if global_occupancy_pct >= 75 else '#2563eb'),
            '#16a34a',
            '#94a3b8'
        ],
        'occupancy_pct': global_occupancy_pct,
    }

    # Chart 3: Historical Arrival Timeline (Last 24h) + 6-hour forecast extrapolation
    # Aggregate historical records across shelters
    recent_history_records = (
        OccupancyHistory.query
        .order_by(OccupancyHistory.recorded_at.desc())
        .limit(50)
        .all()
    )

    trend_labels = []
    trend_occupancy = []
    if recent_history_records:
        # Group into chronological timestamps
        chronological = sorted(recent_history_records, key=lambda h: h.recorded_at)
        for h in chronological[-12:]:
            trend_labels.append(h.recorded_at.strftime('%d %b %H:%M'))
            trend_occupancy.append(h.occupancy)

    chart_trend = {
        'labels': trend_labels,
        'data':   trend_occupancy,
    }

    # ── 8. Role-Aware Filtering & Context Evaluation ──────────────────────────
    is_admin = bool(user and user.role == 'admin')
    is_authority = bool(user and user.role == 'authority')
    is_responder = bool(user and user.role == 'responder')
    is_manager = bool(user and user.role == 'shelter_manager')
    is_citizen = bool(user and user.role == 'citizen')

    can_resolve_alerts = bool(user and (is_admin or is_authority))
    can_dispatch = bool(user and (is_admin or is_authority or is_responder))
    can_manage_shelter = bool(user and (is_admin or is_manager))

    my_shelters: List[Dict[str, Any]] = []
    if is_manager and user:
        my_shelters = [item for item in shelter_cards_data if item['managed_by'] == user.id]

    return {
        # Overall network numbers
        'total_shelters':               total_shelters,
        'active_shelters':              active_count,
        'inactive_shelters':            inactive_count,
        'total_capacity':               total_capacity,
        'total_occupancy':              total_occupancy,
        'total_safe_capacity':          total_safe_capacity,
        'global_occupancy_pct':         global_occupancy_pct,
        'net_safe_available':           net_safe_available,
        'usable_safe_available':        usable_safe_available,
        'total_safe_deficit':           total_safe_deficit,
        'global_network_status':        global_network_status,
        'global_status_label':          global_status_label,

        # Incident and threshold counts
        'critical_shelters_count':      len(critical_shelters),
        'critical_shelters':            critical_shelters,
        'overcrowded_shelters_count':   len(overcrowded_shelters),
        'overcrowded_shelters':         overcrowded_shelters,
        'predicted_overloads_count':    len(predicted_overloads),
        'predicted_overloads':          predicted_overloads,
        'resource_shortages_count':     len(resource_shortages),
        'resource_shortages':           resource_shortages,

        # All shelters list with full annotations
        'shelters_data':                shelter_cards_data,

        # Operational queues and alerts
        'unresolved_alerts':            unresolved_alerts,
        'unresolved_alerts_count':      len(unresolved_alerts),
        'unread_alerts_count':          alert_counts['unread'],
        'critical_alerts_count':        alert_counts['critical'],
        'recent_allocations':           recent_allocations,
        'recent_requests':              recent_requests,
        'pending_requests_count':       pending_requests_count,
        'unallocated_people_count':     unallocated_people_count,

        # Chart payloads
        'chart_shelter_load':           chart_shelter_load,
        'chart_capacity_doughnut':      chart_capacity_doughnut,
        'chart_trend':                  chart_trend,

        # Role context
        'user':                         user,
        'is_admin':                     is_admin,
        'is_authority':                 is_authority,
        'is_responder':                 is_responder,
        'is_manager':                   is_manager,
        'is_citizen':                   is_citizen,
        'can_resolve_alerts':           can_resolve_alerts,
        'can_dispatch':                 can_dispatch,
        'can_manage_shelter':           can_manage_shelter,
        'my_shelters':                  my_shelters,
        'my_shelters_count':            len(my_shelters),
        'hours_ahead':                  hours_ahead,
        'last_updated':                 datetime.utcnow().strftime('%d %b %Y, %H:%M:%S UTC'),
    }
