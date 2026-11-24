"""
routes/alerts.py — Emergency Alerts Management Blueprint.

Routes:
  GET  /alerts/                  → Alert listing with filters (status, severity, type, shelter, read/unread)
  POST /alerts/<id>/read         → Mark an individual alert as read
  POST /alerts/mark-all-read     → Mark all active alerts as read
  POST /alerts/<id>/resolve      → Resolve an alert (Authority / Admin only)
  POST /alerts/scan              → Run immediate system-wide condition scan
  GET  /alerts/api/active        → JSON API endpoint for active alerts & counters
"""

from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, abort
from flask_login import login_required, current_user

from extensions import db
from models.alert import Alert
from models.shelter import Shelter
from services.alerts import (
    evaluate_all_alerts,
    mark_alert_read,
    mark_all_alerts_read,
    resolve_alert,
    get_alert_counts,
)
from utils.decorators import authority_required

alerts_bp = Blueprint('alerts', __name__)


@alerts_bp.route('/')
@login_required
def list_alerts():
    """
    Emergency alerts management view.
    Provides clear information hierarchy, high-contrast severity, and filtering.
    """
    status_filter = request.args.get('status', 'unresolved').strip().lower()
    severity_filter = request.args.get('severity', 'all').strip().lower()
    type_filter = request.args.get('type', 'all').strip().lower()
    shelter_filter = request.args.get('shelter_id', type=int)
    read_filter = request.args.get('read', 'all').strip().lower()
    search_query = request.args.get('q', '').strip()

    # Base query joined with Shelter
    query = Alert.query.outerjoin(Shelter, Alert.shelter_id == Shelter.id)

    # 1. Status Filter
    if status_filter == 'unresolved':
        query = query.filter(Alert.is_resolved == False)
    elif status_filter == 'resolved':
        query = query.filter(Alert.is_resolved == True)

    # 2. Severity Filter
    if severity_filter in ('critical', 'warning', 'info'):
        query = query.filter(Alert.severity == severity_filter)

    # 3. Type Filter
    if type_filter in ('overcrowded', 'critical_capacity', 'predicted_overload', 'resource_shortage', 'shelter_damaged'):
        query = query.filter(Alert.alert_type == type_filter)

    # 4. Shelter Filter
    if shelter_filter:
        query = query.filter(Alert.shelter_id == shelter_filter)

    # 5. Read Filter
    if read_filter == 'unread':
        query = query.filter(Alert.is_read == False)
    elif read_filter == 'read':
        query = query.filter(Alert.is_read == True)

    # 6. Keyword Search
    if search_query:
        query = query.filter(
            db.or_(
                Alert.message.ilike(f"%{search_query}%"),
                Shelter.name.ilike(f"%{search_query}%"),
                Shelter.address.ilike(f"%{search_query}%")
            )
        )

    # Ordering: Critical first, then unread first, then newest
    query = query.order_by(
        Alert.is_resolved.asc(),
        db.case((Alert.severity == 'critical', 1), (Alert.severity == 'warning', 2), else_=3),
        Alert.is_read.asc(),
        Alert.created_at.desc(),
        Alert.id.desc()
    )

    alerts = query.limit(100).all()
    counts = get_alert_counts()
    all_shelters = Shelter.query.order_by(Shelter.name.asc()).all()

    can_resolve = current_user.role in ('authority', 'admin')

    return render_template(
        'alerts/index.html',
        alerts=alerts,
        counts=counts,
        shelters=all_shelters,
        status_filter=status_filter,
        severity_filter=severity_filter,
        type_filter=type_filter,
        shelter_filter=shelter_filter,
        read_filter=read_filter,
        search_query=search_query,
        can_resolve=can_resolve,
    )


@alerts_bp.route('/<int:alert_id>/read', methods=['POST'])
@login_required
def mark_read(alert_id):
    """Mark an individual alert as read."""
    alert = mark_alert_read(alert_id, user=current_user)
    if not alert:
        abort(404)

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'alert_id': alert.id, 'is_read': True})

    flash(f"Alert #{alert.id} marked as read.", "info")
    return redirect(request.referrer or url_for('alerts.list_alerts'))


@alerts_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    """Mark all active alerts as read."""
    count = mark_all_alerts_read(user=current_user)
    flash(f"{count} alerts marked as read.", "info")
    return redirect(request.referrer or url_for('alerts.list_alerts'))


@alerts_bp.route('/<int:alert_id>/resolve', methods=['POST'])
@authority_required
def resolve(alert_id):
    """Authority action to resolve an active alert."""
    notes = request.form.get('notes', '').strip()
    alert = resolve_alert(alert_id, user=current_user, notes=notes if notes else None)
    if not alert:
        abort(404)

    flash(f"Emergency alert #{alert.id} ({alert.type_label}) marked as resolved.", "success")
    return redirect(request.referrer or url_for('alerts.list_alerts'))


@alerts_bp.route('/scan', methods=['POST'])
@authority_required
def scan_network():
    """Trigger an immediate system-wide condition evaluation across all shelters."""
    summary = evaluate_all_alerts(commit=True)
    flash(
        f"Network scan complete: evaluated {summary['shelters_scanned']} shelters. "
        f"{summary['created']} new alert(s) generated, {summary['updated']} alert(s) refreshed, "
        f"{summary['resolved']} condition(s) auto-resolved.",
        "success"
    )
    return redirect(request.referrer or url_for('alerts.list_alerts'))


@alerts_bp.route('/api/active')
@login_required
def api_active():
    """JSON API returning active alert count and recent items."""
    counts = get_alert_counts()
    recent = (
        Alert.query
        .filter_by(is_resolved=False)
        .order_by(
            db.case((Alert.severity == 'critical', 1), (Alert.severity == 'warning', 2), else_=3),
            Alert.created_at.desc()
        )
        .limit(10)
        .all()
    )

    items = []
    for a in recent:
        items.append({
            'id': a.id,
            'shelter_id': a.shelter_id,
            'shelter_name': a.shelter.name if a.shelter else 'System-Wide',
            'alert_type': a.alert_type,
            'type_label': a.type_label,
            'severity': a.severity,
            'message': a.message,
            'is_read': a.is_read,
            'time_ago': a.time_ago,
            'created_at': a.created_at.isoformat() if a.created_at else None,
        })

    return jsonify({
        'counts': counts,
        'alerts': items
    })
