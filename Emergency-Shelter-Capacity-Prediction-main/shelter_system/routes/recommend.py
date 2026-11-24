"""
routes/recommend.py — Shelter Recommendation Blueprint.

Provides endpoints for evaluating candidate shelters for emergency placement:
  - Form interface to select pending requests or run custom emergency simulations
  - Evaluation of registered ShelterRequests
  - Simulation of custom emergency requirements with configurable scoring weights
  - Explainable recommendation results displaying ranked candidates, component scores,
    and auditable rejection reasons for excluded shelters.
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, abort, current_app
from flask_login import current_user
from extensions import db
from utils.decorators import responder_required
from models.request import ShelterRequest
from models.shelter import Shelter
from services.recommendation import evaluate_shelter_candidates, DISCLAIMER_TEXT
from services.redistribution import (
    plan_group_redistribution,
    execute_confirmed_allocation,
)
from services.allocation import (
    confirm_allocation,
    InsufficientCapacityError,
    InvalidAllocationError,
    GroupSizeMismatchError,
)
from services.scoring import get_configured_weights

recommend_bp = Blueprint('recommend', __name__)


class SyntheticRequest:
    """Lightweight object representing a simulated request for the recommendation engine."""
    def __init__(self, **kwargs):
        self.id = None
        self.group_size = int(kwargs.get('group_size', 1))
        self.latitude = float(kwargs.get('latitude', 0.0))
        self.longitude = float(kwargs.get('longitude', 0.0))
        self.location_name = kwargs.get('location_name', 'Simulation Incident Point')
        self.requesting_team = kwargs.get('requesting_team', 'Simulation Unit')
        self.injured_count = int(kwargs.get('injured_count', 0))
        self.elderly_count = int(kwargs.get('elderly_count', 0))
        self.children_count = int(kwargs.get('children_count', 0))
        self.has_disabled = bool(kwargs.get('has_disabled', False))
        self.has_injured = bool(kwargs.get('has_injured', False)) or (self.injured_count > 0)
        self.has_elderly = bool(kwargs.get('has_elderly', False)) or (self.elderly_count > 0)
        self.has_children = bool(kwargs.get('has_children', False)) or (self.children_count > 0)
        self.accessibility_requirements = kwargs.get('accessibility_requirements', '')
        self.medical_requirements = kwargs.get('medical_requirements', '')
        self.other_special_requirements = kwargs.get('other_special_requirements', '')
        self.status = 'simulation'
        self.formatted_time = 'Simulation Mode'

    @property
    def special_needs_list(self):
        items = []
        if self.injured_count > 0:
            items.append(f"Injured: {self.injured_count}")
        elif self.has_injured:
            items.append("Injured")
        if self.elderly_count > 0:
            items.append(f"Elderly: {self.elderly_count}")
        if self.children_count > 0:
            items.append(f"Children: {self.children_count}")
        if self.accessibility_requirements or self.has_disabled:
            items.append("Accessibility / Wheelchair")
        if self.medical_requirements:
            items.append("Medical Support")
        return items


@recommend_bp.route('/')
@responder_required
def recommend_form():
    """
    Recommendation launch pad:
    Lists pending requests ready for evaluation and provides a custom scenario simulator.
    """
    pending_requests = (
        ShelterRequest.query
        .filter(ShelterRequest.status.in_(['pending', 'partially_allocated']))
        .order_by(ShelterRequest.submitted_at.desc())
        .all()
    )
    current_weights = get_configured_weights()
    return render_template(
        'recommend/form.html',
        pending_requests=pending_requests,
        current_weights=current_weights
    )


@recommend_bp.route('/request/<int:request_id>', methods=['GET'])
@responder_required
def recommend_for_request(request_id):
    """
    Run recommendation engine for a specific submitted ShelterRequest.
    """
    req = ShelterRequest.query.get_or_404(request_id)

    # Allow custom weight overrides via query parameters if provided
    custom_weights = None
    if request.args.get('w_dist'):
        try:
            custom_weights = {
                'distance':   float(request.args.get('w_dist', 0.25)),
                'capacity':   float(request.args.get('w_cap',  0.35)),
                'facilities': float(request.args.get('w_fac',  0.20)),
                'resources':  float(request.args.get('w_res',  0.20)),
            }
        except (ValueError, TypeError):
            custom_weights = None

    result = evaluate_shelter_candidates(req, custom_weights=custom_weights)

    return render_template(
        'recommend/results.html',
        req=req,
        result=result,
        is_simulation=False,
        disclaimer=DISCLAIMER_TEXT
    )


@recommend_bp.route('/evaluate', methods=['POST'])
@responder_required
def evaluate_custom():
    """
    Evaluate custom test scenario parameters submitted from the simulation form.
    """
    try:
        group_size = int(request.form.get('group_size', 1))
        if group_size <= 0:
            flash("Group size must be greater than zero.", "danger")
            return redirect(url_for('recommend.recommend_form'))

        lat = float(request.form.get('latitude', 18.5204))
        lon = float(request.form.get('longitude', 73.8567))
        if not (-90.0 <= lat <= 90.0):
            flash("Latitude must be between -90.0 and +90.0.", "danger")
            return redirect(url_for('recommend.recommend_form'))
        if not (-180.0 <= lon <= 180.0):
            flash("Longitude must be between -180.0 and +180.0.", "danger")
            return redirect(url_for('recommend.recommend_form'))

        location_name = request.form.get('location_name', 'Field Incident Site').strip() or 'Field Incident Site'

        injured_count  = max(0, int(request.form.get('injured_count', 0) or 0))
        elderly_count  = max(0, int(request.form.get('elderly_count', 0) or 0))
        children_count = max(0, int(request.form.get('children_count', 0) or 0))

        if injured_count > group_size or elderly_count > group_size or children_count > group_size:
            flash(f"Demographic counts cannot exceed total group size ({group_size}).", "danger")
            return redirect(url_for('recommend.recommend_form'))

        has_disabled = bool(request.form.get('has_disabled'))
        accessibility_requirements = request.form.get('accessibility_requirements', '').strip()
        medical_requirements       = request.form.get('medical_requirements', '').strip()

        # Custom weights if provided
        custom_weights = None
        if request.form.get('weight_distance'):
            try:
                custom_weights = {
                    'distance':   float(request.form.get('weight_distance', 0.25)),
                    'capacity':   float(request.form.get('weight_capacity', 0.35)),
                    'facilities': float(request.form.get('weight_facilities', 0.20)),
                    'resources':  float(request.form.get('weight_resources', 0.20)),
                }
            except (ValueError, TypeError):
                custom_weights = None

        synth_req = SyntheticRequest(
            group_size=group_size,
            latitude=lat,
            longitude=lon,
            location_name=location_name,
            injured_count=injured_count,
            elderly_count=elderly_count,
            children_count=children_count,
            has_disabled=has_disabled,
            accessibility_requirements=accessibility_requirements,
            medical_requirements=medical_requirements,
            other_special_requirements=request.form.get('other_special_requirements', '').strip()
        )

        result = evaluate_shelter_candidates(synth_req, custom_weights=custom_weights)

        return render_template(
            'recommend/results.html',
            req=synth_req,
            result=result,
            is_simulation=True,
            disclaimer=DISCLAIMER_TEXT
        )

    except (ValueError, TypeError) as err:
        flash(f"Invalid input values: {str(err)}", "danger")
        return redirect(url_for('recommend.recommend_form'))


@recommend_bp.route('/api/request/<int:request_id>')
@responder_required
def api_recommend(request_id):
    """
    API endpoint returning JSON evaluation output for integrations or headless testing.
    """
    req = ShelterRequest.query.get_or_404(request_id)
    result = evaluate_shelter_candidates(req)

    return jsonify({
        'request_id': req.id,
        'group_size': req.group_size,
        'recommended_shelter': {
            'shelter_id': result['recommended_shelter']['shelter'].id if result['recommended_shelter'] else None,
            'shelter_name': result['recommended_shelter']['shelter'].name if result['recommended_shelter'] else None,
            'total_score': result['recommended_shelter']['total_score'] if result['recommended_shelter'] else None,
            'distance_km': result['recommended_shelter']['distance_km'] if result['recommended_shelter'] else None,
            'positive_reasons': result['recommended_shelter']['positive_reasons'] if result['recommended_shelter'] else [],
        } if result['recommended_shelter'] else None,
        'total_eligible': result['total_eligible'],
        'total_rejected': result['total_rejected'],
        'disclaimer': result['disclaimer'],
    })


# ── Redistribution Engine Routes ──────────────────────────────────────────────

@recommend_bp.route('/redistribute/request/<int:request_id>', methods=['GET'])
@responder_required
def redistribute_for_request(request_id):
    """
    Evaluates and displays a multi-shelter redistribution plan for a specific request.
    Does NOT mutate occupancy or database status (preview only).
    """
    req = ShelterRequest.query.get_or_404(request_id)
    hours_ahead = request.args.get('hours', type=int)

    plan = plan_group_redistribution(req, hours_ahead=hours_ahead)

    return render_template(
        'recommend/redistribute.html',
        req=req,
        plan=plan,
        is_simulation=False,
        disclaimer=plan['disclaimer']
    )


@recommend_bp.route('/redistribute/simulation', methods=['POST'])
@responder_required
def redistribute_simulation():
    """
    Runs redistribution planning for a custom emergency simulation scenario.
    Does NOT mutate occupancy or database status (preview only).
    """
    try:
        group_size = int(request.form.get('group_size', 1))
        if group_size <= 0:
            flash("Group size must be greater than zero.", "danger")
            return redirect(url_for('recommend.recommend_form'))

        lat = float(request.form.get('latitude', 18.5204))
        lon = float(request.form.get('longitude', 73.8567))
        if not (-90.0 <= lat <= 90.0):
            flash("Latitude must be between -90.0 and +90.0.", "danger")
            return redirect(url_for('recommend.recommend_form'))
        if not (-180.0 <= lon <= 180.0):
            flash("Longitude must be between -180.0 and +180.0.", "danger")
            return redirect(url_for('recommend.recommend_form'))

        location_name = request.form.get('location_name', 'Simulation Incident Site').strip() or 'Simulation Incident Site'

        injured_count  = max(0, int(request.form.get('injured_count', 0) or 0))
        elderly_count  = max(0, int(request.form.get('elderly_count', 0) or 0))
        children_count = max(0, int(request.form.get('children_count', 0) or 0))

        if injured_count > group_size or elderly_count > group_size or children_count > group_size:
            flash(f"Demographic counts cannot exceed total group size ({group_size}).", "danger")
            return redirect(url_for('recommend.recommend_form'))

        has_disabled = bool(request.form.get('has_disabled'))
        accessibility_requirements = request.form.get('accessibility_requirements', '').strip()
        medical_requirements       = request.form.get('medical_requirements', '').strip()

        synth_req = SyntheticRequest(
            group_size=group_size,
            latitude=lat,
            longitude=lon,
            location_name=location_name,
            injured_count=injured_count,
            elderly_count=elderly_count,
            children_count=children_count,
            has_disabled=has_disabled,
            accessibility_requirements=accessibility_requirements,
            medical_requirements=medical_requirements,
            other_special_requirements=request.form.get('other_special_requirements', '').strip()
        )

        plan = plan_group_redistribution(synth_req)

        return render_template(
            'recommend/redistribute.html',
            req=synth_req,
            plan=plan,
            is_simulation=True,
            disclaimer=plan['disclaimer']
        )
    except (ValueError, TypeError) as err:
        flash(f"Invalid input parameters: {str(err)}", "danger")
        return redirect(url_for('recommend.recommend_form'))


@recommend_bp.route('/confirm/<int:request_id>', methods=['POST'])
@responder_required
def confirm_single_allocation(request_id):
    """
    Confirms placement of an entire requested group into a single selected shelter.
    Executes inside a database transaction with pessimistic row-level locking (SELECT ... FOR UPDATE)
    to guarantee safe capacity and prevent over-allocation.
    """
    req = ShelterRequest.query.get_or_404(request_id)

    if req.status == 'allocated':
        flash("This request has already been fully allocated.", "info")
        return redirect(url_for('requests.request_detail', request_id=req.id))

    shelter_id = request.form.get('shelter_id', type=int)
    if not shelter_id:
        flash("Target shelter ID must be provided.", "danger")
        return redirect(url_for('recommend.recommend_for_request', request_id=req.id))

    shelter = db.session.get(Shelter, shelter_id)
    if not shelter:
        flash(f"Shelter #{shelter_id} not found.", "danger")
        return redirect(url_for('recommend.recommend_for_request', request_id=req.id))

    notes = request.form.get('notes', '').strip() or None

    try:
        allocation_plan = [{
            'shelter_id': shelter.id,
            'allocated_count': req.group_size,
        }]
        result = confirm_allocation(
            request_id=req.id,
            allocations=allocation_plan,
            confirmed_by_user_id=current_user.id if current_user.is_authenticated else None,
            notes=notes or f"Direct allocation: all {req.group_size} evacuee(s) placed in {shelter.name}",
        )
        flash(
            f"Allocation confirmed! {req.group_size} evacuee(s) successfully placed in '{shelter.name}'. "
            f"Shelter occupancy and audit history updated.",
            "success"
        )
        return redirect(url_for('requests.request_detail', request_id=req.id))
    except (InsufficientCapacityError, InvalidAllocationError, GroupSizeMismatchError) as err:
        flash(f"Allocation rejected: {str(err)}", "danger")
        return redirect(url_for('recommend.recommend_for_request', request_id=req.id))
    except Exception:
        current_app.logger.exception("Unexpected error during direct allocation confirmation")
        flash("Allocation transaction failed due to an unexpected system error. Please try again or contact support.", "danger")
        return redirect(url_for('recommend.recommend_for_request', request_id=req.id))


@recommend_bp.route('/redistribute/confirm/<int:request_id>', methods=['POST'])
@responder_required
def confirm_redistribution(request_id):
    """
    Explicitly confirms and executes the proposed allocation plan.
    This is the ONLY action that mutates shelter occupancy and database status.
    Guaranteed by pessimistic row-level locking.
    """
    req = ShelterRequest.query.get_or_404(request_id)

    if req.status == 'allocated':
        flash("This request has already been fully allocated.", "info")
        return redirect(url_for('requests.request_detail', request_id=req.id))

    plan = plan_group_redistribution(req)

    if not plan.get('is_possible'):
        flash(f"Cannot confirm allocation: current safe capacity cannot accommodate the full group. {plan.get('explanation')}", "danger")
        return redirect(url_for('recommend.redistribute_for_request', request_id=req.id))

    try:
        notes = request.form.get('notes', '').strip() or None
        success, allocations = execute_confirmed_allocation(
            request_id=req.id,
            plan=plan,
            confirmed_by_user_id=current_user.id if current_user.is_authenticated else None,
            notes=notes
        )
        flash(f"Allocation confirmed! {plan['total_allocated']} evacuees successfully partitioned across {len(allocations)} shelters. Safe occupancies updated.", "success")
        return redirect(url_for('requests.request_detail', request_id=req.id))
    except (InsufficientCapacityError, InvalidAllocationError, GroupSizeMismatchError) as err:
        flash(f"Allocation rejected: {str(err)}", "danger")
        return redirect(url_for('recommend.redistribute_for_request', request_id=req.id))
    except Exception:
        current_app.logger.exception("Unexpected error during redistribution plan execution")
        flash("Allocation execution failed due to an unexpected system error. Please try again or contact support.", "danger")
        return redirect(url_for('recommend.redistribute_for_request', request_id=req.id))


@recommend_bp.route('/api/redistribute/<int:request_id>')
@responder_required
def api_redistribute(request_id):
    """
    JSON API endpoint returning the multi-shelter redistribution plan.
    """
    req = ShelterRequest.query.get_or_404(request_id)
    hours_ahead = request.args.get('hours', type=int)
    plan = plan_group_redistribution(req, hours_ahead=hours_ahead)

    return jsonify({
        'request_id': req.id,
        'group_size': req.group_size,
        'is_possible': plan['is_possible'],
        'total_requested': plan['total_requested'],
        'total_allocated': plan['total_allocated'],
        'unallocated_count': plan['unallocated_count'],
        'total_network_safe_capacity': plan['total_network_safe_capacity'],
        'allocations': [
            {
                'shelter_id': a['shelter_id'],
                'shelter_name': a['shelter_name'],
                'allocated_count': a['allocated_count'],
                'current_occupancy': a['current_occupancy'],
                'safe_capacity': a['safe_capacity'],
                'max_capacity': a['max_capacity'],
                'safe_available_before': a['safe_available_before'],
                'safe_available_after': a['safe_available_after'],
                'projected_occupancy': a['projected_occupancy'],
                'projected_pct': a['projected_pct'],
                'distance_km': a['distance_km'],
                'score': a['score'],
                'rank': a['rank'],
                'reasons': a['reasons'],
            }
            for a in plan['allocations']
        ],
        'candidate_shelters': [
            {
                'shelter_id': c['shelter_id'],
                'name': c['name'],
                'safe_available_capacity': c['safe_available_capacity'],
                'score': c['score'],
                'rank': c['rank'],
                'distance_km': c['distance_km'],
            }
            for c in plan['candidate_shelters']
        ],
        'unsuitable_shelters': [
            {
                'shelter_id': u['shelter'].id,
                'name': u['shelter'].name,
                'reason': u['reason'],
                'category': u['category'],
            }
            for u in plan['unsuitable_shelters']
        ],
        'explanation': plan['explanation'],
        'disclaimer': plan['disclaimer'],
    })

