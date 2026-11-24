"""
routes/requests.py — Shelter Request Management.

Routes:
  GET  /requests/             — List all requests (filter by status, search)
  GET  /requests/new          — Emergency request creation form
  POST /requests/new          — Submit new shelter request
  GET  /requests/<id>         — View request details
  POST /requests/<id>/status  — Update request status (e.g. cancel)

Validation Rules:
  - group_size must be an integer greater than zero
  - latitude (-90 to 90) and longitude (-180 to 180)
  - people counts (injured, elderly, children) must be non-negative (>= 0)
  - clear, segmented emergency UI structure
"""

from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_required, current_user

from extensions import db
from models.request import ShelterRequest, REQUEST_STATUS_LABELS, REQUEST_STATUS_BADGES
from models.user import User

requests_bp = Blueprint('requests', __name__)

STATUS_CHOICES = ['pending', 'allocated', 'partially_allocated', 'cancelled']


def _validate_request_form(form_data):
    """
    Validate emergency shelter request form data.
    Returns: (errors: dict, clean_data: dict)
    """
    errors = {}
    data = {}

    # 1. Group Size (Mandatory: > 0)
    raw_size = form_data.get('group_size', '').strip()
    try:
        size = int(raw_size)
        if size <= 0:
            errors['group_size'] = 'Group size must be greater than zero.'
        else:
            data['group_size'] = size
    except (ValueError, TypeError):
        errors['group_size'] = 'Please enter a valid whole number for group size.'

    # 2. Location & Coordinates (Mandatory)
    loc_name = form_data.get('location_name', '').strip()
    if len(loc_name) > 200:
        errors['location_name'] = 'Location name must be 200 characters or fewer.'
    else:
        data['location_name'] = loc_name if loc_name else 'Unspecified Location'

    raw_lat = form_data.get('latitude', '').strip()
    try:
        lat = float(raw_lat)
        if not (-90.0 <= lat <= 90.0):
            errors['latitude'] = 'Latitude must be between -90.0 and +90.0.'
        else:
            data['latitude'] = lat
    except (ValueError, TypeError):
        errors['latitude'] = 'Enter a valid latitude coordinate (e.g. 18.5204).'

    raw_lng = form_data.get('longitude', '').strip()
    try:
        lng = float(raw_lng)
        if not (-180.0 <= lng <= 180.0):
            errors['longitude'] = 'Longitude must be between -180.0 and +180.0.'
        else:
            data['longitude'] = lng
    except (ValueError, TypeError):
        errors['longitude'] = 'Enter a valid longitude coordinate (e.g. 73.8567).'

    # 3. Requesting Team & Contact Phone (Optional but recommended)
    req_team = form_data.get('requesting_team', '').strip()
    if len(req_team) > 150:
        errors['requesting_team'] = 'Requesting team must be 150 characters or fewer.'
    else:
        data['requesting_team'] = req_team

    phone = form_data.get('contact_phone', '').strip()
    if len(phone) > 50:
        errors['contact_phone'] = 'Contact phone must be 50 characters or fewer.'
    else:
        data['contact_phone'] = phone

    # 4. Demographic Counts (Must be >= 0)
    def parse_count(field_name, label):
        raw = form_data.get(field_name, '0').strip() or '0'
        try:
            val = int(raw)
            if val < 0:
                errors[field_name] = f'{label} cannot be negative.'
                return 0
            return val
        except (ValueError, TypeError):
            errors[field_name] = f'{label} must be a non-negative whole number.'
            return 0

    data['injured_count']  = parse_count('injured_count',  'Injured people count')
    data['elderly_count']  = parse_count('elderly_count',  'Elderly people count')
    data['children_count'] = parse_count('children_count', 'Children count')

    # Sanity check: individual counts should not individually exceed total group size if valid
    if 'group_size' in data:
        for f, label in [('injured_count', 'Injured count'),
                         ('elderly_count', 'Elderly count'),
                         ('children_count', 'Children count')]:
            if data[f] > data['group_size']:
                errors[f] = f'{label} ({data[f]}) cannot exceed total group size ({data["group_size"]}).'

    # 5. Requirements & Notes
    data['accessibility_requirements'] = form_data.get('accessibility_requirements', '').strip() or None
    data['medical_requirements']       = form_data.get('medical_requirements', '').strip() or None
    data['other_special_requirements'] = form_data.get('other_special_requirements', '').strip() or None
    data['notes']                      = form_data.get('notes', '').strip() or None

    return errors, data


# ── Routes ────────────────────────────────────────────────────────────────────

@requests_bp.route('/')
@login_required
def list_requests():
    """List shelter requests with filtering by status and search."""
    status_filter = request.args.get('status', '').strip()
    search = request.args.get('q', '').strip()

    query = ShelterRequest.query

    # Non-responders/citizens only see requests they submitted themselves
    if not current_user.can_operate() and current_user.role != 'admin':
        query = query.filter(ShelterRequest.submitted_by == current_user.id)

    # Status filter
    if status_filter and status_filter in STATUS_CHOICES:
        query = query.filter(ShelterRequest.status == status_filter)

    # Search by location or team or submitter
    if search:
        query = query.join(User, ShelterRequest.submitted_by == User.id).filter(
            db.or_(
                ShelterRequest.location_name.ilike(f'%{search}%'),
                ShelterRequest.requesting_team.ilike(f'%{search}%'),
                ShelterRequest.notes.ilike(f'%{search}%'),
                User.full_name.ilike(f'%{search}%')
            )
        )

    requests_list = query.order_by(ShelterRequest.submitted_at.desc()).all()

    # Calculate overall stats
    all_base = ShelterRequest.query
    if not current_user.can_operate() and current_user.role != 'admin':
        all_base = all_base.filter(ShelterRequest.submitted_by == current_user.id)
    all_reqs = all_base.all()

    stats = {
        'total':             len(all_reqs),
        'pending':           sum(1 for r in all_reqs if r.status == 'pending'),
        'allocated':         sum(1 for r in all_reqs if r.status in ('allocated', 'partially_allocated')),
        'cancelled':         sum(1 for r in all_reqs if r.status == 'cancelled'),
        'total_people':      sum(r.group_size for r in all_reqs),
        'pending_people':    sum(r.group_size for r in all_reqs if r.status == 'pending'),
        'special_needs_reqs':sum(1 for r in all_reqs if r.has_special_needs),
    }

    return render_template(
        'requests/list.html',
        requests=requests_list,
        stats=stats,
        status_filter=status_filter,
        search=search,
        STATUS_CHOICES=STATUS_CHOICES,
        STATUS_LABELS=REQUEST_STATUS_LABELS,
    )


@requests_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_request():
    """Create a new emergency shelter request."""
    if request.method == 'POST':
        errors, data = _validate_request_form(request.form)

        if errors:
            flash('Please check the form for errors and correct the highlighted fields.', 'danger')
            return render_template(
                'requests/form.html',
                errors=errors,
                form_data=request.form,
                default_team=current_user.full_name,
            )

        # Create new ShelterRequest
        req = ShelterRequest(
            submitted_by=current_user.id,
            group_size=data['group_size'],
            latitude=data['latitude'],
            longitude=data['longitude'],
            location_name=data['location_name'],
            requesting_team=data['requesting_team'] or current_user.full_name,
            contact_phone=data['contact_phone'],
            injured_count=data['injured_count'],
            elderly_count=data['elderly_count'],
            children_count=data['children_count'],
            accessibility_requirements=data['accessibility_requirements'],
            medical_requirements=data['medical_requirements'],
            other_special_requirements=data['other_special_requirements'],
            notes=data['notes'],
            status='pending',
            submitted_at=datetime.utcnow(),
        )

        # Sync legacy boolean flags for constraint evaluation in later stages
        req.sync_boolean_flags()

        db.session.add(req)
        db.session.commit()

        flash(
            f'Emergency request #{req.id} for {req.group_size} people created successfully.',
            'success'
        )
        return redirect(url_for('requests.request_detail', request_id=req.id))

    # GET
    default_team = current_user.full_name
    if current_user.role == 'responder':
        default_team = f"Response Unit — {current_user.full_name}"

    return render_template(
        'requests/form.html',
        errors={},
        form_data={},
        default_team=default_team,
    )


@requests_bp.route('/<int:request_id>')
@login_required
def request_detail(request_id):
    """View details of a specific shelter request."""
    req = db.session.get(ShelterRequest, request_id)
    if req is None:
        abort(404)

    # Permission check: citizens can only view their own requests
    if not current_user.can_operate() and current_user.role != 'admin':
        if req.submitted_by != current_user.id:
            abort(403)

    return render_template(
        'requests/detail.html',
        req=req,
        STATUS_LABELS=REQUEST_STATUS_LABELS,
    )


@requests_bp.route('/<int:request_id>/status', methods=['POST'])
@login_required
def update_request_status(request_id):
    """Update status of a request (e.g. cancel)."""
    req = db.session.get(ShelterRequest, request_id)
    if req is None:
        abort(404)

    # Permission check: submitter, responder, or admin can cancel
    if not current_user.can_operate() and current_user.role != 'admin':
        if req.submitted_by != current_user.id:
            abort(403)

    new_status = request.form.get('status', '').strip()
    if new_status not in STATUS_CHOICES:
        flash('Invalid status provided.', 'danger')
        return redirect(url_for('requests.request_detail', request_id=request_id))

    old_status = req.status
    req.status = new_status
    req.updated_at = datetime.utcnow()
    db.session.commit()

    flash(f'Request #{req.id} status updated from {old_status} to {new_status}.', 'success')
    return redirect(url_for('requests.request_detail', request_id=request_id))
