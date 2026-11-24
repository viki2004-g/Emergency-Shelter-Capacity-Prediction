"""
services/scoring.py — Configurable weighted scoring engine for shelters.

Calculates normalized 0–100 scores across 4 key dimensions:
  1. Distance   — Proximity of the shelter to the requesting group
  2. Capacity   — Post-allocation safe headroom & future occupancy overload risk
  3. Facilities — Breadth of amenities with contextual bonuses for group demographics
  4. Resources  — Stock of consumable supplies (beds, food, water, medicine, blankets)

Final Composite Score:
  Score = (W_dist * S_dist) + (W_cap * S_cap) + (W_fac * S_fac) + (W_res * S_res)

Weights are fully configurable via Flask config / environment variables.
"""

from typing import Dict, Any, Optional


# Default scoring weights (sum to 1.0)
DEFAULT_WEIGHTS = {
    'distance':   0.25,
    'capacity':   0.35,
    'facilities': 0.20,
    'resources':  0.20,
}


def get_configured_weights(custom_weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """
    Retrieve normalized recommendation weights.
    Order of precedence:
      1. Explicitly passed custom_weights dictionary
      2. Flask application config (WEIGHT_DISTANCE, etc.)
      3. DEFAULT_WEIGHTS

    Always ensures the weights sum to 1.0 via normalization.
    """
    if custom_weights:
        raw = {
            'distance':   float(custom_weights.get('distance',   DEFAULT_WEIGHTS['distance'])),
            'capacity':   float(custom_weights.get('capacity',   DEFAULT_WEIGHTS['capacity'])),
            'facilities': float(custom_weights.get('facilities', DEFAULT_WEIGHTS['facilities'])),
            'resources':  float(custom_weights.get('resources',  DEFAULT_WEIGHTS['resources'])),
        }
    else:
        try:
            from flask import current_app
            raw = {
                'distance':   float(current_app.config.get('WEIGHT_DISTANCE',   DEFAULT_WEIGHTS['distance'])),
                'capacity':   float(current_app.config.get('WEIGHT_CAPACITY',   DEFAULT_WEIGHTS['capacity'])),
                'facilities': float(current_app.config.get('WEIGHT_FACILITIES', DEFAULT_WEIGHTS['facilities'])),
                'resources':  float(current_app.config.get('WEIGHT_RESOURCES',  DEFAULT_WEIGHTS['resources'])),
            }
        except Exception:
            raw = dict(DEFAULT_WEIGHTS)

    # Clean negative values
    for k in raw:
        if raw[k] < 0:
            raw[k] = 0.0

    total = sum(raw.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)

    # Normalize so sum is exactly 1.0
    return {k: round(v / total, 4) for k, v in raw.items()}


def calculate_distance_score(distance_km: float, max_km: float = 50.0) -> float:
    """
    Score shelter proximity on a 0–100 scale.
    0 km -> 100.0 points
    max_km (50 km) or greater -> 0.0 points
    Linear degradation across distance horizon.
    """
    try:
        dist = max(0.0, float(distance_km))
        if dist >= max_km:
            return 0.0
        score = 100.0 * (1.0 - (dist / max_km))
        return round(max(0.0, min(100.0, score)), 1)
    except (TypeError, ValueError):
        return 0.0


def calculate_capacity_score(shelter, group_size: int, prediction: Optional[Dict[str, Any]] = None) -> float:
    """
    Score shelter capacity safety on a 0–100 scale.
    Evaluates safe headroom remaining AFTER placing the group.
    Adjusts score based on predicted future occupancy velocity.

    Headroom = (safe_available_capacity - group_size) / safe_capacity
    """
    try:
        group_size = max(1, int(group_size))
        safe_cap = shelter.safe_capacity
        safe_avail = shelter.safe_available_capacity

        if safe_cap <= 0:
            return 0.0

        # Remaining safe buffer after accommodating this group
        remaining_safe_buffer = safe_avail - group_size
        if remaining_safe_buffer < 0:
            # If less than safe capacity, score starts below 50 proportional to remaining
            base_score = max(0.0, 50.0 * (shelter.available_capacity - group_size) / max(1, shelter.max_capacity))
        else:
            # Shelter comfortably holds the group within safe limits
            # Headroom ratio between 0.0 and 1.0
            ratio = min(1.0, remaining_safe_buffer / safe_cap)
            base_score = 50.0 + (ratio * 50.0)

        # Incorporate future occupancy trend heuristic when available
        adjustment = 0.0
        if prediction and prediction.get('has_prediction'):
            risk = prediction.get('overload_risk', 'low')
            if risk == 'critical':
                adjustment = -30.0  # Predicted to breach 100% capacity
            elif risk == 'high':
                adjustment = -15.0  # Predicted to exceed safe planning threshold
            elif risk == 'moderate':
                adjustment = -5.0
            elif risk == 'low':
                adjustment = +10.0  # Stable or declining trend

        final_score = base_score + adjustment
        return round(max(0.0, min(100.0, final_score)), 1)
    except Exception:
        return 50.0


def calculate_facilities_score(shelter, request: Optional[Any] = None) -> float:
    """
    Score physical amenities on a 0–100 scale.
    Base: 8 standard amenities (10 points each -> 80 max).
    Bonuses: Contextual demographic matches (family area for kids, electricity/toilets for elderly).
    """
    facility = getattr(shelter, 'facility', None)
    if not facility:
        return 0.0

    score = 0.0

    # Standard facility checklist (up to 80 pts)
    if facility.has_medical_support:
        score += 12.0
    if facility.has_wheelchair_access:
        score += 12.0
    if facility.has_running_water:
        score += 10.0
    if facility.has_electricity:
        score += 10.0
    if facility.has_toilets:
        score += 10.0
    if facility.has_food:
        score += 10.0
    if facility.has_kitchen:
        score += 8.0
    if facility.has_family_area:
        score += 8.0

    # Contextual demographic bonuses (up to 20 pts)
    if request:
        ch_cnt = int(getattr(request, 'children_count', 0) or 0)
        has_children = (ch_cnt > 0) or bool(getattr(request, 'has_children', False))
        if has_children and (facility.has_family_area or facility.has_kitchen):
            score += 10.0

        eld_cnt = int(getattr(request, 'elderly_count', 0) or 0)
        has_elderly = (eld_cnt > 0) or bool(getattr(request, 'has_elderly', False))
        if has_elderly and facility.has_toilets and facility.has_electricity:
            score += 10.0

    return round(max(0.0, min(100.0, score)), 1)


def calculate_resources_score(shelter, request: Optional[Any] = None) -> float:
    """
    Score consumable resources (beds, food, water, medicine, blankets) on a 0–100 scale
    relative to the size and needs of the requesting group.
    """
    resource = getattr(shelter, 'resource', None)
    if not resource:
        return 0.0

    group_size = int(getattr(request, 'group_size', 10) or 10)
    group_size = max(1, group_size)

    injured_count = int(getattr(request, 'injured_count', 0) or 0)

    # 1. Beds (25 points): Ratio of available beds to group members
    beds_ratio = min(1.0, resource.beds_available / group_size)
    score_beds = beds_ratio * 25.0

    # 2. Food (25 points): Target 3 meals/portions per group member
    food_target = max(1, group_size * 3)
    food_ratio = min(1.0, resource.food_portions / food_target)
    score_food = food_ratio * 25.0

    # 3. Water (25 points): Target 10 litres per group member
    water_target = max(1, group_size * 10)
    water_ratio = min(1.0, resource.water_litres / water_target)
    score_water = water_ratio * 25.0

    # 4. Blankets (15 points): 1 per group member
    blanket_ratio = min(1.0, resource.blankets / group_size)
    score_blankets = blanket_ratio * 15.0

    # 5. Medicine kits (10 points): Proportional to injured or baseline
    med_target = max(2, injured_count)
    med_ratio = min(1.0, resource.medicine_kits / med_target)
    score_medicine = med_ratio * 10.0

    total = score_beds + score_food + score_water + score_blankets + score_medicine
    return round(max(0.0, min(100.0, total)), 1)


def calculate_weighted_score(
    dist_score: float,
    cap_score: float,
    fac_score: float,
    res_score: float,
    weights: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Combine the 4 component scores into a single weighted total score (0.0 to 100.0).
    Returns a dictionary with the composite score, normalized weights, and component contributions.
    """
    w = get_configured_weights(weights)

    weighted_total = (
        (w['distance']   * dist_score) +
        (w['capacity']   * cap_score) +
        (w['facilities'] * fac_score) +
        (w['resources']  * res_score)
    )

    total_score = round(max(0.0, min(100.0, weighted_total)), 1)

    return {
        'total_score': total_score,
        'weights': w,
        'components': {
            'distance': {
                'raw_score': dist_score,
                'weight': w['distance'],
                'weighted_contribution': round(dist_score * w['distance'], 1)
            },
            'capacity': {
                'raw_score': cap_score,
                'weight': w['capacity'],
                'weighted_contribution': round(cap_score * w['capacity'], 1)
            },
            'facilities': {
                'raw_score': fac_score,
                'weight': w['facilities'],
                'weighted_contribution': round(fac_score * w['facilities'], 1)
            },
            'resources': {
                'raw_score': res_score,
                'weight': w['resources'],
                'weighted_contribution': round(res_score * w['resources'], 1)
            },
        }
    }
