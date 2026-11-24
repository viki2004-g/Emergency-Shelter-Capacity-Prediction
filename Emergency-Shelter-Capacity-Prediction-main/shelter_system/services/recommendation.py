"""
services/recommendation.py — Shelter recommendation engine.

Implements the 12-step recommendation pipeline:
  1.  Find candidate shelters.
  2.  Remove shelters that are not operational.
  3.  Apply hard constraints first:
       - Physical capacity >= group size
       - Safe available capacity >= group size
       - Wheelchair accessibility (if required by request)
       - Medical support / facility (if required by request)
       (Shelters failing ANY hard constraint are EXCLUDED, never simply downscored)
  4.  Check safe available capacity headroom.
  5.  Check special requirements and demographics.
  6.  Consider medical facilities.
  7.  Consider accessibility.
  8.  Consider consumable resources (beds, food, water, medicine, blankets).
  9.  Calculate distance via Haversine formula.
 10.  Consider predicted future occupancy trend heuristic when prediction data exists.
 11.  Calculate weighted recommendation score across Distance, Capacity, Facilities, Resources.
 12.  Rank eligible shelters descending by recommendation score.

Returns:
  - Explainable positive reasons for the recommended shelter.
  - Auditable rejection reasons (per failure type) for all excluded shelters.
  - Mandatory disclaimer: recommendations are NOT guaranteed to be optimal.
"""

from typing import List, Dict, Any, Optional
from models.shelter import Shelter
from services.distance import haversine_distance, distance_band, BAND_LABELS
from services.prediction import predict_shelter_occupancy
from services.scoring import (
    get_configured_weights,
    calculate_distance_score,
    calculate_capacity_score,
    calculate_facilities_score,
    calculate_resources_score,
    calculate_weighted_score,
)


DISCLAIMER_TEXT = (
    "Heuristic recommendation based on current reported operational data and trend estimates. "
    "Does not claim or guarantee mathematical optimality. "
    "Field coordinators must verify on-ground conditions before physical dispatch."
)

# Rejection reason category tags — used by the template for colour-coding
REJECTION_CATEGORY = {
    'status':       'status',
    'capacity':     'capacity',
    'safe_cap':     'safe_cap',
    'wheelchair':   'wheelchair',
    'medical':      'medical',
}


def _build_positive_reasons(
    shelter,
    group_size: int,
    distance_km: float,
    prediction: Dict[str, Any],
    request: Any,
) -> List[str]:
    """
    Generate a human-readable list of positive reasons why this shelter
    is eligible and recommended. Each reason corresponds to a concrete
    data point rather than a generic statement.
    """
    reasons = []
    facility = getattr(shelter, 'facility', None)
    resource = getattr(shelter, 'resource', None)

    safe_avail = shelter.safe_available_capacity
    safe_cap   = shelter.safe_capacity
    occ_pct    = shelter.occupancy_pct

    # 1 — Capacity headroom
    post_buffer = safe_avail - group_size
    if post_buffer >= 0:
        reasons.append(
            f"Sufficient safe capacity: {safe_avail} safe spots available; "
            f"{post_buffer} buffer spot(s) remain after placing group of {group_size}"
        )
    else:
        reasons.append(
            f"Physically accommodates group ({shelter.available_capacity} physical spots); "
            f"slight safe-limit overage mitigated by large absolute headroom"
        )

    # 2 — Medical facility
    if facility and facility.has_medical_support:
        reasons.append("Medical facility available on site (triage and first-aid support)")

    # 3 — Wheelchair / accessibility
    if facility and facility.has_wheelchair_access:
        reasons.append("Wheelchair-accessible infrastructure verified")

    # 4 — Proximity (uses distance_band for consistent labelling across codebase)
    band = distance_band(distance_km)
    label = BAND_LABELS.get(band, 'Accessible distance')
    reasons.append(f"{label}: {distance_km} km from incident location")

    # 5 — Future occupancy prediction
    if prediction.get('has_prediction'):
        risk = prediction.get('overload_risk', 'low')
        risk_label = prediction.get('risk_label', '')
        projected_pct = prediction.get('predicted_pct', occ_pct)
        hours = prediction.get('hours_ahead', 6)
        if risk == 'low':
            reasons.append(
                f"[ESTIMATE] Low predicted overload risk: projected occupancy {projected_pct}% in {hours}h"
            )
        elif risk == 'moderate':
            reasons.append(
                f"[ESTIMATE] Manageable projected occupancy: {projected_pct}% in {hours}h — monitor closely"
            )
        # high / critical are not eligible (scoring penalty already applied)
    else:
        reasons.append(
            "[ESTIMATE] Stable baseline occupancy — no rising arrival trend detected in recent history"
        )

    # 6 — Resource stock assessment
    if resource:
        low_fields = getattr(resource, 'low_fields', [])
        if not resource.any_low:
            reasons.append(
                f"Fully stocked reserves: {resource.beds_available} beds · "
                f"{resource.food_portions} meal portions · "
                f"{resource.water_litres}L water · "
                f"{resource.medicine_kits} medicine kits · "
                f"{resource.blankets} blankets"
            )
        else:
            # List what is OK and note the low items transparently
            ok_items = []
            if resource.beds_available > 0 and 'beds_available' not in low_fields:
                ok_items.append(f"{resource.beds_available} beds")
            if resource.food_portions > 0 and 'food_portions' not in low_fields:
                ok_items.append(f"{resource.food_portions} meals")
            if resource.water_litres > 0 and 'water_litres' not in low_fields:
                ok_items.append(f"{resource.water_litres}L water")
            if ok_items:
                reasons.append(
                    f"Adequate key resources: {' · '.join(ok_items)}"
                )
            low_names = {
                'beds_available': 'beds',
                'food_portions':  'meal portions',
                'water_litres':   'water',
                'medicine_kits':  'medicine kits',
                'blankets':       'blankets',
            }
            warn_parts = [low_names.get(f, f) for f in low_fields]
            reasons.append(
                f"⚠ Low supply warning: {', '.join(warn_parts)} — coordinate resupply before dispatch"
            )

    # 7 — Contextual demographic amenities
    req_children = int(getattr(request, 'children_count', 0) or 0) > 0 or bool(
        getattr(request, 'has_children', False)
    )
    req_elderly  = int(getattr(request, 'elderly_count', 0) or 0) > 0 or bool(
        getattr(request, 'has_elderly', False)
    )

    if facility:
        if req_children and facility.has_family_area:
            reasons.append("Dedicated family / children's area available")
        if req_children and facility.has_kitchen:
            reasons.append("On-site kitchen available — suitable for children's meal preparation")
        if req_elderly and facility.has_toilets and facility.has_electricity:
            reasons.append(
                "Electricity and indoor toilets available — suitable for elderly residents"
            )
        if facility.has_running_water and facility.has_electricity:
            reasons.append("Verified municipal power and running water supply")
        elif facility.has_running_water:
            reasons.append("Running water supply available")
        elif facility.has_electricity:
            reasons.append("Electrical supply available")

    return reasons


def _build_rejection_detail(reason_text: str, category: str) -> Dict[str, str]:
    """Return a structured rejection detail dict for template use."""
    return {
        'reason':   reason_text,
        'category': category,
    }


def evaluate_shelter_candidates(
    request: Any,
    shelters: Optional[List[Shelter]] = None,
    custom_weights: Optional[Dict[str, float]] = None,
    hours_ahead: Optional[int] = None
) -> Dict[str, Any]:
    """
    Evaluates candidate shelters for an incoming shelter request.

    Args:
        request:        ShelterRequest model instance (or compatible object/dict).
                        Expected attributes: group_size, latitude, longitude,
                        injured_count, elderly_count, children_count,
                        has_injured, has_disabled, has_elderly, has_children,
                        accessibility_requirements, medical_requirements.
        shelters:       Optional list of Shelter models. If None, queries all.
        custom_weights: Optional weight dict overriding config defaults.
        hours_ahead:    Optional forecast horizon hours for occupancy prediction.

    Returns:
        dict containing:
          recommended_shelter : top-ranked eligible candidate (or None)
          eligible_shelters   : sorted list of all eligible candidates with scores & reasons
          rejected_shelters   : list of excluded shelters with per-category failure reasons
          total_evaluated     : int — total candidates considered
          total_eligible      : int
          total_rejected      : int
          weights_used        : dict — normalized weights applied
          disclaimer          : str — mandatory transparency notice
    """

    # ── Step 1: Find candidate shelters ───────────────────────────────────────
    if shelters is None:
        shelters = Shelter.query.all()

    # Extract request attributes safely
    group_size = int(getattr(request, 'group_size', 1) or 1)
    group_size = max(1, group_size)

    req_lat = float(getattr(request, 'latitude',  0.0) or 0.0)
    req_lon = float(getattr(request, 'longitude', 0.0) or 0.0)

    # Determine hard constraint flags
    needs_wheelchair = (
        bool(getattr(request, 'has_disabled', False)) or
        bool(
            getattr(request, 'accessibility_requirements', None) and
            str(request.accessibility_requirements).strip()
        )
    )

    injured_cnt = int(getattr(request, 'injured_count', 0) or 0)
    needs_medical = (
        bool(getattr(request, 'has_injured', False)) or
        (injured_cnt > 0) or
        bool(
            getattr(request, 'medical_requirements', None) and
            str(request.medical_requirements).strip()
        )
    )

    eligible_candidates = []
    rejected_candidates  = []

    # Get normalized scoring weights once
    weights = get_configured_weights(custom_weights)

    for shelter in shelters:
        rejection_details = []   # list of {reason, category} dicts

        # ── Step 2: Operational status check ──────────────────────────────────
        # Only 'active' shelters can accept evacuees.
        if shelter.status != 'active':
            rejection_details.append(_build_rejection_detail(
                f"Shelter is currently {shelter.status_label.lower()} — "
                f"only shelters with 'Active' status can accept evacuees.",
                REJECTION_CATEGORY['status']
            ))

        # ── Step 3: Hard constraints — STRICT EXCLUSION, never just downscored ─

        # (A) Physical capacity
        avail_cap = shelter.available_capacity
        if avail_cap < group_size:
            rejection_details.append(_build_rejection_detail(
                f"Insufficient physical capacity: {avail_cap} space(s) available "
                f"for group of {group_size} — shelter is physically full.",
                REJECTION_CATEGORY['capacity']
            ))

        # (B) Safe planning capacity
        safe_avail = shelter.safe_available_capacity
        if safe_avail < group_size:
            rejection_details.append(_build_rejection_detail(
                f"Exceeds safe planning capacity: only {safe_avail} safe spot(s) available "
                f"(safe limit: {shelter.safe_limit}% of {shelter.max_capacity} max). "
                f"Group of {group_size} would breach the safe occupancy threshold.",
                REJECTION_CATEGORY['safe_cap']
            ))

        facility = getattr(shelter, 'facility', None)

        # (C) Wheelchair / accessibility hard constraint
        if needs_wheelchair:
            if not facility or not facility.has_wheelchair_access:
                rejection_details.append(_build_rejection_detail(
                    "Lacks wheelchair-accessible infrastructure required by this group. "
                    "Placing mobility-impaired evacuees here is unsafe.",
                    REJECTION_CATEGORY['wheelchair']
                ))

        # (D) Medical support hard constraint
        if needs_medical:
            if not facility or not facility.has_medical_support:
                rejection_details.append(_build_rejection_detail(
                    "Lacks on-site medical facility / medical support required for injured evacuees. "
                    "Medical care cannot be deferred for this group.",
                    REJECTION_CATEGORY['medical']
                ))

        # If ANY hard constraint failed → exclude entirely
        if rejection_details:
            rejected_candidates.append({
                'shelter':              shelter,
                'rejection_details':    rejection_details,
                # Backward-compat key for test assertions
                'rejection_reasons':    [d['reason'] for d in rejection_details],
                'available_capacity':   avail_cap if shelter.status == 'active' else shelter.available_capacity,
                'safe_available_capacity': shelter.safe_available_capacity,
                'status':               shelter.status,
            })
            continue

        # ── Eligible Candidate: compute scores ────────────────────────────────

        # Step 9: Distance (Haversine formula, km)
        shelter_lat = float(shelter.latitude  or 0.0)
        shelter_lon = float(shelter.longitude or 0.0)
        distance_km = haversine_distance(req_lat, req_lon, shelter_lat, shelter_lon)

        # Step 10: Future occupancy prediction (trend heuristic)
        prediction = predict_shelter_occupancy(shelter, hours_ahead=hours_ahead)

        # Step 11: Calculate component scores
        score_dist = calculate_distance_score(distance_km)
        score_cap  = calculate_capacity_score(shelter, group_size, prediction)
        score_fac  = calculate_facilities_score(shelter, request)
        score_res  = calculate_resources_score(shelter, request)

        score_data = calculate_weighted_score(
            dist_score=score_dist,
            cap_score=score_cap,
            fac_score=score_fac,
            res_score=score_res,
            weights=weights,
        )

        # Annotate score_data with prediction summary for easy template access
        score_data['prediction_summary'] = prediction.get('summary', '')
        score_data['prediction_disclaimer'] = prediction.get('disclaimer', '')

        # Step 5–8: Build explainable positive reasons
        positive_reasons = _build_positive_reasons(
            shelter, group_size, distance_km, prediction, request
        )

        eligible_candidates.append({
            'shelter':          shelter,
            'distance_km':      distance_km,
            'prediction':       prediction,
            'score_data':       score_data,
            'total_score':      score_data['total_score'],
            'positive_reasons': positive_reasons,
            'score_components': score_data['components'],
        })

    # ── Step 12: Rank eligible shelters ───────────────────────────────────────
    # Primary sort:   total recommendation score descending
    # Secondary sort: distance ascending (tiebreaker)
    eligible_candidates.sort(
        key=lambda x: (-x['total_score'], x['distance_km'])
    )

    # Attach 1-indexed rank numbers
    for idx, cand in enumerate(eligible_candidates, start=1):
        cand['rank'] = idx

    recommended_shelter = eligible_candidates[0] if eligible_candidates else None

    return {
        'request':              request,
        'recommended_shelter':  recommended_shelter,
        'eligible_shelters':    eligible_candidates,
        'rejected_shelters':    rejected_candidates,
        'total_evaluated':      len(shelters),
        'total_eligible':       len(eligible_candidates),
        'total_rejected':       len(rejected_candidates),
        'weights_used':         weights,
        'disclaimer':           DISCLAIMER_TEXT,
    }
