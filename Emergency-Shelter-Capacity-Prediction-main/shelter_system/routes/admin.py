"""
routes/admin.py — System Administration & User Governance Blueprint.

Provides role-protected endpoints for system administrators:
  - System Overview KPI Dashboard
  - User Directory with Search and Multi-Criteria Filtering
  - Account Status Management (Active/Inactive Toggle with Self-Lockout Guard)
  - Role Allocation & Governance (with Self-Demotion Guard)
  - Emergency Shelter Network Capacity Overview
  - System Operational Parameters & Security Configuration View
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import current_user

from models.user import ROLE_LABELS
from services.admin import (
    VALID_ROLES,
    get_admin_dashboard_stats,
    get_filtered_users,
    get_shelters_overview,
    toggle_user_active_status,
    change_user_role,
    get_user_metadata,
    get_system_configuration,
)
from utils.decorators import admin_required

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
@admin_required
def admin_panel():
    """
    Main Administration Dashboard & Governance Portal.
    Accessible strictly by users with the 'admin' role.
    """
    search = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '').strip()
    status_filter = request.args.get('status', '').strip()
    active_tab = request.args.get('tab', 'users').strip()

    stats = get_admin_dashboard_stats()
    users = get_filtered_users(search=search, role_filter=role_filter, status_filter=status_filter)
    shelters = get_shelters_overview()
    system_config = get_system_configuration()

    return render_template(
        'admin/users.html',
        stats=stats,
        users=users,
        shelters=shelters,
        system_config=system_config,
        search=search,
        role_filter=role_filter,
        status_filter=status_filter,
        active_tab=active_tab,
        valid_roles=VALID_ROLES,
        role_labels=ROLE_LABELS,
    )


@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_status(user_id: int):
    """
    Toggles user active/inactive state.
    Guarded against administrator self-deactivation.
    """
    success, message = toggle_user_active_status(user_id, current_user.id)
    flash(message, 'success' if success else 'danger')

    return redirect(url_for(
        'admin.admin_panel',
        q=request.form.get('q', ''),
        role=request.form.get('role', ''),
        status=request.form.get('status', ''),
        tab='users'
    ))


@admin_bp.route('/users/<int:user_id>/change-role', methods=['POST'])
@admin_required
def update_role(user_id: int):
    """
    Updates a user's access role.
    Guarded against administrator self-demotion.
    """
    new_role = request.form.get('new_role', '').strip()
    success, message = change_user_role(user_id, new_role, current_user.id)
    flash(message, 'success' if success else 'danger')

    return redirect(url_for(
        'admin.admin_panel',
        q=request.form.get('q', ''),
        role=request.form.get('role', ''),
        status=request.form.get('status', ''),
        tab='users'
    ))


@admin_bp.route('/users/<int:user_id>/detail', methods=['GET'])
@admin_required
def user_detail(user_id: int):
    """
    Returns sanitized metadata for a single user in JSON format.
    Passswords and password hashes are strictly omitted.
    """
    metadata = get_user_metadata(user_id)
    if not metadata:
        return jsonify({'error': 'User not found'}), 404

    return jsonify(metadata)
