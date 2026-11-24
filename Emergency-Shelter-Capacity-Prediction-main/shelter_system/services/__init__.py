"""
Services package.
Each module contains business logic that is independent of Flask routes.
Routes call services; services do not import routes.

Modules:
  capacity.py       — available capacity, safe limits, occupancy status
  distance.py       — Haversine geographic distance calculation
  prediction.py     — future occupancy forecasting and overload risk heuristic
  scoring.py        — configurable weighted scoring engine
  recommendation.py — 12-step recommendation pipeline with hard constraint exclusions
"""

from services.capacity import (
    calculate_available_capacity,
    calculate_occupancy_percentage,
    calculate_safe_capacity,
    calculate_safe_available_capacity,
    determine_occupancy_status,
)

from services.distance import haversine_distance

from services.prediction import (
    predict_shelter_occupancy,
    get_default_forecast_hours,
    predict_all_shelters,
    generate_forecast_series,
    get_prediction_assumptions,
    PREDICTION_DISCLAIMER,
)

from services.scoring import (
    get_configured_weights,
    calculate_distance_score,
    calculate_capacity_score,
    calculate_facilities_score,
    calculate_resources_score,
    calculate_weighted_score,
)

from services.recommendation import (
    evaluate_shelter_candidates,
    DISCLAIMER_TEXT,
)

from services.redistribution import (
    plan_group_redistribution,
    execute_confirmed_allocation,
)

from services.allocation import (
    confirm_allocation,
    AllocationError,
    InsufficientCapacityError,
    InvalidAllocationError,
    GroupSizeMismatchError,
)

from services.dashboard import (
    get_dashboard_summary,
)

from services.alerts import (
    evaluate_shelter_alerts,
    evaluate_all_alerts,
    create_or_update_alert,
    auto_resolve_alert,
    mark_alert_read,
    mark_all_alerts_read,
    resolve_alert,
    get_alert_counts,
    get_active_alerts,
)

__all__ = [
    'calculate_available_capacity',
    'calculate_occupancy_percentage',
    'calculate_safe_capacity',
    'calculate_safe_available_capacity',
    'determine_occupancy_status',
    'haversine_distance',
    'predict_shelter_occupancy',
    'get_default_forecast_hours',
    'predict_all_shelters',
    'generate_forecast_series',
    'get_prediction_assumptions',
    'PREDICTION_DISCLAIMER',
    'get_configured_weights',
    'calculate_distance_score',
    'calculate_capacity_score',
    'calculate_facilities_score',
    'calculate_resources_score',
    'calculate_weighted_score',
    'evaluate_shelter_candidates',
    'DISCLAIMER_TEXT',
    'plan_group_redistribution',
    'execute_confirmed_allocation',
    'confirm_allocation',
    'AllocationError',
    'InsufficientCapacityError',
    'InvalidAllocationError',
    'GroupSizeMismatchError',
    'get_dashboard_summary',
    'evaluate_shelter_alerts',
    'evaluate_all_alerts',
    'create_or_update_alert',
    'auto_resolve_alert',
    'mark_alert_read',
    'mark_all_alerts_read',
    'resolve_alert',
    'get_alert_counts',
    'get_active_alerts',
]


