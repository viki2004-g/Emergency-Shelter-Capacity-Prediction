"""
routes/shelters.py — Shelter management routes.

Routes:
  GET  /shelters/                      — List all shelters (search + filter)
  GET  /shelters/occupancy             — Network occupancy overview & tracking (Stage 6)
  GET  /shelters/new                   — Create shelter form
  POST /shelters/new                   — Create shelter (submit)
  GET  /shelters/<id>                  — Shelter detail
  GET  /shelters/<id>/occupancy        — Dedicated shelter occupancy tracking & history (Stage 6)
  GET  /shelters/<id>/edit             — Edit shelter form
  POST /shelters/<id>/edit             — Edit shelter (submit)
  POST /shelters/<id>/status           — Quick status change
  POST /shelters/<id>/occupancy        — Update current occupancy & record history (Stage 6)
  POST /shelters/<id>/facilities       — Update facility flags (Stage 5)
  POST /shelters/<id>/resources        — Update resource quantities (Stage 5)

Access rules:
  view list / detail : login_required (all authenticated users)
  create / edit      : manager_required (shelter_manager + admin)
  shelter_manager    : can only edit shelters assigned to them
  admin              : can edit all shelters
"""

from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_required, current_user

from extensions import db
from models import Shelter, ShelterFacility, Resource, OccupancyHistory, User
from utils.decorators import manager_required
from services.capacity import (
    calculate_available_capacity,
    calculate_occupancy_percentage,
    calculate_safe_capacity,
    calculate_safe_available_capacity,
    determine_occupancy_status,
    get_status_label,
    get_configured_thresholds,
    get_configured_safe_limit_pct,
    record_occupancy_change,
)

shelters_bp = Blueprint('shelters', __name__)

# Valid operational status values (must match DB ENUM)
STATUS_CHOICES = ['active', 'inactive', 'full', 'damaged', 'closed']


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_managers():
    """Return all users who can be assigned as shelter manager."""
    return (User.query
            .filter(User.role.in_(['shelter_manager', 'admin']))
            .order_by(User.full_name)
            .all())


def _check_manager_owns(shelter):
    """
    For shelter_managers: abort(403) if they don't manage this shelter.
    Admins skip this check.
    """
    if current_user.role == 'shelter_manager' and shelter.managed_by != current_user.id:
        abort(403)


def _attach_deltas(history_list):
    """
    Given a list of OccupancyHistory records sorted by recorded_at DESC,
    attach a 'delta' attribute (difference from older adjacent record).
    """
    for i, h in enumerate(history_list):
        if i + 1 < len(history_list):
            h.delta = h.occupancy - history_list[i + 1].occupancy
        else:
            h.delta = 0
    return history_list


def _validate_shelter_form(form, shelter_id=None):
    """
    Validate shelter form fields.
    Returns (errors: dict, data: dict).
    errors is empty on success.
    """
    errors = {}
    data = {}

    # ── Name ──────────────────────────────────────────────────────────────────
    name = form.get('name', '').strip()
    if not name:
        errors['name'] = 'Shelter name is required.'
    elif len(name) > 150:
        errors['name'] = 'Name must be 150 characters or fewer.'
    else:
        # Unique name check (exclude this shelter on edit)
        clash = Shelter.query.filter(
            Shelter.name == name,
            Shelter.id != shelter_id
        ).first()
        if clash:
            errors['name'] = 'A shelter with this name already exists.'
        else:
            data['name'] = name

    # ── Address ───────────────────────────────────────────────────────────────
    address = form.get('address', '').strip()
    if not address:
        errors['address'] = 'Address is required.'
    else:
        data['address'] = address

    # ── Latitude ──────────────────────────────────────────────────────────────
    try:
        lat = float(form.get('latitude', ''))
        if not (-90 <= lat <= 90):
            errors['latitude'] = 'Latitude must be between -90 and 90.'
        else:
            data['latitude'] = lat
    except (ValueError, TypeError):
        errors['latitude'] = 'Enter a valid latitude (example: 18.5167).'

    # ── Longitude ─────────────────────────────────────────────────────────────
    try:
        lng = float(form.get('longitude', ''))
        if not (-180 <= lng <= 180):
            errors['longitude'] = 'Longitude must be between -180 and 180.'
        else:
            data['longitude'] = lng
    except (ValueError, TypeError):
        errors['longitude'] = 'Enter a valid longitude (example: 73.8389).'

    # ── Max Capacity ──────────────────────────────────────────────────────────
    try:
        max_cap = int(form.get('max_capacity', ''))
        if max_cap <= 0:
            errors['max_capacity'] = 'Max capacity must be a positive number.'
        else:
            data['max_capacity'] = max_cap
    except (ValueError, TypeError):
        errors['max_capacity'] = 'Enter a whole number for max capacity.'

    # ── Current Occupancy ─────────────────────────────────────────────────────
    try:
        occ = int(form.get('current_occupancy', 0))
        if occ < 0:
            errors['current_occupancy'] = 'Occupancy cannot be negative.'
        else:
            data['current_occupancy'] = occ
    except (ValueError, TypeError):
        errors['current_occupancy'] = 'Enter a whole number for current occupancy.'

    # ── Safe Limit Percentage (optional) ─────────────────────────────────────
    raw_pct = form.get('safe_limit_pct', '').strip()
    if raw_pct:
        try:
            pct = int(raw_pct)
            if not (50 <= pct <= 100):
                errors['safe_limit_pct'] = 'Safe limit must be between 50 and 100.'
            else:
                data['safe_limit_pct'] = pct
        except ValueError:
            errors['safe_limit_pct'] = 'Enter a whole number between 50 and 100.'
    else:
        data['safe_limit_pct'] = None  # use system default

    # ── Status ────────────────────────────────────────────────────────────────
    status = form.get('status', 'active')
    if status not in STATUS_CHOICES:
        errors['status'] = 'Select a valid status.'
    else:
        data['status'] = status

    # ── Manager (optional) ────────────────────────────────────────────────────
    mgr_raw = form.get('managed_by', '').strip()
    if mgr_raw:
        try:
            data['managed_by'] = int(mgr_raw)
        except (ValueError, TypeError):
            errors['managed_by'] = 'Invalid shelter manager selected.'
    else:
        data['managed_by'] = None

    # ── Notes (optional) ──────────────────────────────────────────────────────
    data['notes'] = form.get('notes', '').strip() or None

    return errors, data


def _extract_facilities(form):
    """Extract facility boolean flags from a POST form."""
    return {
        'has_medical_support':   form.get('has_medical_support')   == 'on',
        'has_food':              form.get('has_food')              == 'on',
        'has_wheelchair_access': form.get('has_wheelchair_access') == 'on',
        'has_electricity':       form.get('has_electricity')       == 'on',
        'has_toilets':           form.get('has_toilets')           == 'on',
        'has_running_water':     form.get('has_running_water')     == 'on',
        'has_kitchen':           form.get('has_kitchen')           == 'on',
        'has_family_area':       form.get('has_family_area')       == 'on',
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@shelters_bp.route('/')
@login_required
def list_shelters():
    """Shelter list with server-side search and status filter."""
    search        = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip()

    # Stats always use the full (unfiltered) dataset
    all_shelters = Shelter.query.all()
    total_cap  = sum(s.max_capacity      for s in all_shelters)
    total_occ  = sum(s.current_occupancy for s in all_shelters)
    stats = {
        'total':                len(all_shelters),
        'total_capacity':       total_cap,
        'total_occupied':       total_occ,
        'total_available':      total_cap - total_occ,
        'total_safe_capacity':  sum(s.safe_capacity for s in all_shelters),
        'total_safe_available': sum(s.safe_available_capacity for s in all_shelters),
        'critical_count':       sum(1 for s in all_shelters
                                    if s.capacity_status in ('critical', 'overcrowded')),
        'active_count':         sum(1 for s in all_shelters if s.status == 'active'),
    }

    # Apply search and filter
    query = Shelter.query
    if search:
        query = query.filter(
            db.or_(
                Shelter.name.ilike(f'%{search}%'),
                Shelter.address.ilike(f'%{search}%')
            )
        )
    if status_filter and status_filter in STATUS_CHOICES:
        query = query.filter(Shelter.status == status_filter)

    shelters = query.order_by(Shelter.name).all()

    return render_template(
        'shelters/list.html',
        shelters=shelters,
        stats=stats,
        search=search,
        status_filter=status_filter,
        STATUS_CHOICES=STATUS_CHOICES,
    )


@shelters_bp.route('/occupancy')
@login_required
def occupancy_overview():
    """System-wide Occupancy Tracking dashboard."""
    shelters = Shelter.query.order_by(Shelter.name).all()
    thresholds = get_configured_thresholds()

    total_capacity       = sum(s.max_capacity for s in shelters)
    total_occupancy      = sum(s.current_occupancy for s in shelters)
    total_available      = total_capacity - total_occupancy
    total_safe_capacity  = sum(s.safe_capacity for s in shelters)
    total_safe_available = sum(s.safe_available_capacity for s in shelters)
    overall_pct          = calculate_occupancy_percentage(total_occupancy, total_capacity)

    status_counts = {
        'safe':        sum(1 for s in shelters if s.capacity_status == 'safe'),
        'moderate':    sum(1 for s in shelters if s.capacity_status == 'moderate'),
        'high':        sum(1 for s in shelters if s.capacity_status == 'high'),
        'critical':    sum(1 for s in shelters if s.capacity_status == 'critical'),
        'overcrowded': sum(1 for s in shelters if s.capacity_status == 'overcrowded'),
    }

    stats = {
        'total_shelters':       len(shelters),
        'total_capacity':       total_capacity,
        'total_occupancy':      total_occupancy,
        'total_available':      total_available,
        'total_safe_capacity':  total_safe_capacity,
        'total_safe_available': total_safe_available,
        'overall_pct':          overall_pct,
        'status_counts':        status_counts,
    }

    return render_template(
        'shelters/occupancy_overview.html',
        shelters=shelters,
        stats=stats,
        thresholds=thresholds,
        global_safe_limit=get_configured_safe_limit_pct(),
    )


@shelters_bp.route('/new', methods=['GET', 'POST'])
@manager_required
def new_shelter():
    """Create a new shelter."""
    managers = _get_managers()

    if request.method == 'POST':
        errors, data = _validate_shelter_form(request.form)
        facilities   = _extract_facilities(request.form)

        if errors:
            flash('Please correct the highlighted errors.', 'danger')
            return render_template(
                'shelters/form.html',
                shelter=None, managers=managers,
                errors=errors, form_data=request.form,
                facilities=facilities, title='New Shelter',
                STATUS_CHOICES=STATUS_CHOICES,
            )

        # Create shelter
        shelter = Shelter(**data)
        db.session.add(shelter)
        db.session.flush()  # populate shelter.id before FK records

        # Create related records (facility, resources, first history entry)
        db.session.add(ShelterFacility(shelter_id=shelter.id, **facilities))
        db.session.add(Resource(shelter_id=shelter.id))
        db.session.add(OccupancyHistory(
            shelter_id=shelter.id,
            occupancy=shelter.current_occupancy,
            recorded_by=current_user.id,
        ))
        db.session.commit()

        flash(f'Shelter "{shelter.name}" created successfully.', 'success')
        return redirect(url_for('shelters.shelter_detail', shelter_id=shelter.id))

    # GET — pre-select current user as manager if they're a shelter_manager
    default_mgr = current_user.id if current_user.role == 'shelter_manager' else None
    return render_template(
        'shelters/form.html',
        shelter=None, managers=managers,
        errors={}, form_data={'managed_by': default_mgr},
        facilities={}, title='New Shelter',
        STATUS_CHOICES=STATUS_CHOICES,
    )


@shelters_bp.route('/<int:shelter_id>')
@login_required
def shelter_detail(shelter_id):
    """Shelter detail page."""
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)

    history = (OccupancyHistory.query
               .filter_by(shelter_id=shelter_id)
               .order_by(OccupancyHistory.recorded_at.desc())
               .limit(15)
               .all())
    _attach_deltas(history)

    return render_template(
        'shelters/detail.html',
        shelter=shelter,
        history=history,
        thresholds=get_configured_thresholds(),
        STATUS_CHOICES=STATUS_CHOICES,
    )


@shelters_bp.route('/<int:shelter_id>/edit', methods=['GET', 'POST'])
@manager_required
def edit_shelter(shelter_id):
    """Edit an existing shelter."""
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)
    _check_manager_owns(shelter)

    managers = _get_managers()

    if request.method == 'POST':
        old_occ      = shelter.current_occupancy
        errors, data = _validate_shelter_form(request.form, shelter_id=shelter_id)
        facilities   = _extract_facilities(request.form)

        if errors:
            flash('Please correct the highlighted errors.', 'danger')
            return render_template(
                'shelters/form.html',
                shelter=shelter, managers=managers,
                errors=errors, form_data=request.form,
                facilities=facilities, title=f'Edit — {shelter.name}',
                STATUS_CHOICES=STATUS_CHOICES,
            )

        # Update shelter fields
        for field, value in data.items():
            setattr(shelter, field, value)

        # Update or create facility record
        if shelter.facility:
            for field, value in facilities.items():
                setattr(shelter.facility, field, value)
        else:
            db.session.add(ShelterFacility(shelter_id=shelter.id, **facilities))

        # Record occupancy change in history
        new_occ = data.get('current_occupancy', old_occ)
        if new_occ != old_occ:
            db.session.add(OccupancyHistory(
                shelter_id=shelter.id,
                occupancy=new_occ,
                recorded_by=current_user.id,
            ))

        db.session.commit()
        flash(f'"{shelter.name}" updated successfully.', 'success')
        return redirect(url_for('shelters.shelter_detail', shelter_id=shelter.id))

    # GET — pre-fill facility flags from the existing record
    fac_data = {}
    if shelter.facility:
        fac_data = {
            f: getattr(shelter.facility, f)
            for f in ('has_medical_support', 'has_wheelchair_access', 'has_electricity',
                      'has_toilets', 'has_running_water', 'has_kitchen', 'has_family_area')
        }

    return render_template(
        'shelters/form.html',
        shelter=shelter, managers=managers,
        errors={}, form_data={},
        facilities=fac_data, title=f'Edit — {shelter.name}',
        STATUS_CHOICES=STATUS_CHOICES,
    )


@shelters_bp.route('/<int:shelter_id>/status', methods=['POST'])
@manager_required
def update_status(shelter_id):
    """Quick operational status change from the detail page."""
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)
    _check_manager_owns(shelter)

    new_status = request.form.get('status', '').strip()
    if new_status not in STATUS_CHOICES:
        flash('Invalid status value.', 'danger')
        return redirect(url_for('shelters.shelter_detail', shelter_id=shelter_id))

    old_status    = shelter.status
    shelter.status = new_status
    db.session.commit()

    flash(f'Status changed from "{old_status}" to "{new_status}".', 'success')
    return redirect(url_for('shelters.shelter_detail', shelter_id=shelter_id))


@shelters_bp.route('/<int:shelter_id>/occupancy', methods=['GET'])
@login_required
def shelter_occupancy(shelter_id):
    """Detailed Occupancy Tracking and History for a single shelter."""
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)

    history = (OccupancyHistory.query
               .filter_by(shelter_id=shelter_id)
               .order_by(OccupancyHistory.recorded_at.desc())
               .all())
    _attach_deltas(history)

    # Calculate trend metrics if history exists
    analytics = {}
    if history:
        counts = [h.occupancy for h in history]
        analytics['min_occupancy'] = min(counts)
        analytics['max_occupancy'] = max(counts)
        analytics['avg_occupancy'] = round(sum(counts) / len(counts), 1)
        analytics['total_updates'] = len(history)
        if len(counts) >= 2:
            analytics['net_change'] = counts[0] - counts[-1]
        else:
            analytics['net_change'] = 0

    return render_template(
        'shelters/occupancy_detail.html',
        shelter=shelter,
        history=history,
        analytics=analytics,
        thresholds=get_configured_thresholds(),
        STATUS_CHOICES=STATUS_CHOICES,
    )


@shelters_bp.route('/<int:shelter_id>/occupancy', methods=['POST'])
@manager_required
def update_occupancy(shelter_id):
    """Update current occupancy and add an immutable history record."""
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)
    _check_manager_owns(shelter)

    raw_val = request.form.get('current_occupancy', '').strip()
    try:
        new_occ = int(raw_val)
        if new_occ < 0:
            raise ValueError('negative')
    except (ValueError, TypeError):
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Enter a valid non-negative whole number for occupancy.'}), 400
        flash('Enter a valid non-negative whole number for occupancy.', 'danger')
        return redirect(url_for('shelters.shelter_detail', shelter_id=shelter_id))

    old_occ = shelter.current_occupancy
    diff = new_occ - old_occ

    changed, hist = record_occupancy_change(shelter, new_occ, user_id=current_user.id, force=True)

    sign = f'+{diff}' if diff >= 0 else str(diff)
    msg = (f'Occupancy updated to {new_occ}/{shelter.max_capacity} ({sign} people). '
           f'Status: {shelter.capacity_status_label} ({shelter.occupancy_pct}%). '
           f'Safe Available: {shelter.safe_available_capacity}.')

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'message': msg,
            'metrics': shelter.capacity_metrics,
            'history_entry': hist.to_dict() if hist else None
        })

    flash(msg, 'success' if new_occ <= shelter.safe_capacity else ('warning' if new_occ <= shelter.max_capacity else 'danger'))

    # Redirect back to caller (detail or occupancy view)
    referer = request.referrer or ''
    if '/occupancy' in referer:
        return redirect(url_for('shelters.shelter_occupancy', shelter_id=shelter_id))
    return redirect(url_for('shelters.shelter_detail', shelter_id=shelter_id))


# ── Stage 5: Facilities & Resources ──────────────────────────────────────────

# All facility flag names — must match both the model columns and form field names
FACILITY_FLAGS = [
    'has_medical_support',
    'has_food',
    'has_wheelchair_access',
    'has_electricity',
    'has_toilets',
    'has_running_water',
    'has_kitchen',
    'has_family_area',
]

# All resource quantity field names — must match model columns and form field names
RESOURCE_FIELDS = [
    'beds_available',
    'food_portions',
    'water_litres',
    'medicine_kits',
    'blankets',
]


@shelters_bp.route('/<int:shelter_id>/facilities', methods=['POST'])
@manager_required
def update_facilities(shelter_id):
    """
    Update the facility flags for a shelter.
    Accepts a POST form with checkbox fields (present = True, absent = False).
    """
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)
    _check_manager_owns(shelter)

    # Create facility record if missing (should not happen for seeded data)
    fac = shelter.facility
    if fac is None:
        fac = ShelterFacility(shelter_id=shelter.id)
        db.session.add(fac)

    # Update each flag from the form (checkbox: present = on, absent = missing)
    for flag in FACILITY_FLAGS:
        setattr(fac, flag, request.form.get(flag) == 'on')

    fac.notes      = request.form.get('facility_notes', '').strip() or None
    fac.updated_by = current_user.id
    db.session.commit()

    active = fac.count_available
    flash(f'Facilities updated — {active} of {len(FACILITY_FLAGS)} available.', 'success')
    return redirect(url_for('shelters.shelter_detail', shelter_id=shelter_id))


@shelters_bp.route('/<int:shelter_id>/resources', methods=['POST'])
@manager_required
def update_resources(shelter_id):
    """
    Update resource quantities for a shelter.
    All quantities must be non-negative integers.
    Collects all errors before returning.
    """
    shelter = db.session.get(Shelter, shelter_id)
    if shelter is None:
        abort(404)
    _check_manager_owns(shelter)

    errors  = []
    values  = {}

    for field in RESOURCE_FIELDS:
        raw = request.form.get(field, '').strip()
        try:
            val = int(raw)
            if val < 0:
                errors.append(f'{field.replace("_", " ").title()} cannot be negative.')
            else:
                values[field] = val
        except (ValueError, TypeError):
            errors.append(
                f'{field.replace("_", " ").title()} must be a whole number (got: "{raw}").'
            )

    if errors:
        for msg in errors:
            flash(msg, 'danger')
        return redirect(url_for('shelters.shelter_detail', shelter_id=shelter_id))

    # Create resource record if missing
    res = shelter.resource
    if res is None:
        res = Resource(shelter_id=shelter.id)
        db.session.add(res)

    for field, val in values.items():
        setattr(res, field, val)

    res.notes      = request.form.get('resource_notes', '').strip() or None
    res.updated_by = current_user.id
    db.session.commit()

    low = res.low_fields
    if low:
        low_names = ', '.join(f.replace('_', ' ') for f in low)
        flash(
            f'Resources saved. Low stock warning: {low_names}.', 'warning'
        )
    else:
        flash('Resources updated successfully.', 'success')

    return redirect(url_for('shelters.shelter_detail', shelter_id=shelter_id))
