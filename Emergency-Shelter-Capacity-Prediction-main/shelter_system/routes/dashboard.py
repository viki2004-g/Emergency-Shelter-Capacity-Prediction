"""
routes/dashboard.py — Main Emergency Management Dashboard Blueprint.

Provides mission-critical situational awareness endpoints for the EOC:
  - GET  /dashboard/                  → Comprehensive role-aware emergency management dashboard
  - POST /dashboard/alerts/<id>/resolve → Authority action to resolve active emergency warnings
  - GET  /dashboard/api/stats          → JSON API for real-time dashboard analytics & chart telemetry
"""

from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, abort
from flask_login import login_required, current_user

from extensions import db
from models.alert import Alert
from services.dashboard import get_dashboard_summary
from utils.decorators import authority_required

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def dashboard():
    """
    Main Emergency Operations Dashboard.
    Displays real-time capacity, occupancy, predictions, alerts, and recent operational feeds.
    Content and actions adapt based on the user's role (admin, authority, responder, shelter_manager, citizen).
    """
    hours_ahead = request.args.get('hours', type=int, default=6)
    active_filter = request.args.get('filter', default='all').strip().lower()

    # Query all metrics from MySQL database via dashboard service
    summary_data = get_dashboard_summary(user=current_user, hours_ahead=hours_ahead)

    # Filter shelter list based on active tab/filter if specified
    filtered_shelters = summary_data['shelters_data']
    if active_filter == 'critical':
        filtered_shelters = summary_data['critical_shelters']
    elif active_filter == 'overcrowded':
        filtered_shelters = summary_data['overcrowded_shelters']
    elif active_filter == 'overload_risk':
        filtered_shelters = summary_data['predicted_overloads']
    elif active_filter == 'shortage':
        filtered_shelters = summary_data['resource_shortages']
    elif active_filter == 'my_shelters' and summary_data['is_manager']:
        filtered_shelters = summary_data['my_shelters']

    return render_template(
        'dashboard/index.html',
        d=summary_data,
        shelters=filtered_shelters,
        active_filter=active_filter,
        hours_ahead=hours_ahead,
    )


@dashboard_bp.route('/alerts/<int:alert_id>/resolve', methods=['POST'])
@authority_required
def resolve_alert(alert_id):
    """
    Action endpoint for authorities/admins to mark an active emergency alert as resolved.
    """
    alert = db.session.get(Alert, alert_id)
    if alert is None:
        abort(404)

    alert.is_resolved = True
    alert.resolved_by = current_user.id
    alert.resolved_at = datetime.utcnow()
    db.session.commit()

    type_name = alert.alert_type.replace('_', ' ').title()
    flash(f"Emergency alert #{alert.id} ({type_name}) marked as resolved.", "success")
    return redirect(url_for('dashboard.dashboard'))


@dashboard_bp.route('/api/stats')
@login_required
def api_stats():
    """
    JSON API endpoint returning real-time operational statistics and Chart.js datasets.
    """
    hours_ahead = request.args.get('hours', type=int, default=6)
    data = get_dashboard_summary(user=current_user, hours_ahead=hours_ahead)

    return jsonify({
        'total_shelters':               data['total_shelters'],
        'active_shelters':              data['active_shelters'],
        'inactive_shelters':            data['inactive_shelters'],
        'total_capacity':               data['total_capacity'],
        'total_occupancy':              data['total_occupancy'],
        'total_safe_capacity':          data['total_safe_capacity'],
        'global_occupancy_pct':         data['global_occupancy_pct'],
        'net_safe_available':           data['net_safe_available'],
        'usable_safe_available':        data['usable_safe_available'],
        'total_safe_deficit':           data['total_safe_deficit'],
        'global_network_status':        data['global_network_status'],
        'global_status_label':          data['global_status_label'],
        'critical_shelters_count':      data['critical_shelters_count'],
        'overcrowded_shelters_count':   data['overcrowded_shelters_count'],
        'predicted_overloads_count':    data['predicted_overloads_count'],
        'resource_shortages_count':     data['resource_shortages_count'],
        'unresolved_alerts_count':      data['unresolved_alerts_count'],
        'pending_requests_count':       data['pending_requests_count'],
        'unallocated_people_count':     data['unallocated_people_count'],
        'chart_shelter_load':           data['chart_shelter_load'],
        'chart_capacity_doughnut':      data['chart_capacity_doughnut'],
        'chart_trend':                  data['chart_trend'],
        'last_updated':                 data['last_updated'],
    })
