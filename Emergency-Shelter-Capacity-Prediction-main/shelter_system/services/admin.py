"""
services/admin.py — System Administration Service Layer.

Provides business logic for the Administrative Dashboard and User Governance:
  - Aggregate administrative metrics (users, roles, shelters, capacity)
  - User filtering, searching, and pagination/ordering
  - Secure role modification with self-demotion prevention
  - Account activation/deactivation with self-lockout prevention
  - Compact administrative shelter network overview
  - Real system configuration parameter extraction
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from flask import current_app
from sqlalchemy import or_

from extensions import db
from models.user import User, ROLE_LABELS
from models.shelter import Shelter
from models.request import ShelterRequest
from services.capacity import determine_occupancy_status, get_configured_safe_limit_pct


VALID_ROLES = ('admin', 'authority', 'responder', 'shelter_manager', 'citizen')


def get_admin_dashboard_stats() -> Dict[str, Any]:
    """
    Computes system-level summary metrics across users and shelter infrastructure.
    Uses existing business logic and database models.
    """
    # ── User Statistics ───────────────────────────────────────────────────────
    all_users = User.query.all()
    total_users = len(all_users)
    active_users = sum(1 for u in all_users if u.is_active)
    inactive_users = total_users - active_users

    # Count users by role
    users_by_role = {role: 0 for role in VALID_ROLES}
    for u in all_users:
        if u.role in users_by_role:
            users_by_role[u.role] += 1

    # ── Shelter Network Statistics ────────────────────────────────────────────
    all_shelters = Shelter.query.order_by(Shelter.name.asc()).all()
    total_shelters = len(all_shelters)
    active_shelters = [s for s in all_shelters if s.status == 'active']
    active_shelters_count = len(active_shelters)

    total_capacity = sum(s.max_capacity for s in active_shelters)
    total_occupancy = sum(s.current_occupancy for s in active_shelters)

    # Critical / overcrowded shelter count using existing threshold logic
    critical_or_overcrowded_count = 0
    for s in all_shelters:
        status = determine_occupancy_status(s.occupancy_pct)
        if status in ('critical', 'overcrowded') or s.current_occupancy > s.max_capacity:
            critical_or_overcrowded_count += 1

    overall_utilization = (
        round((total_occupancy / total_capacity) * 100, 1)
        if total_capacity > 0 else 0.0
    )

    return {
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'users_by_role': users_by_role,
        'total_shelters': total_shelters,
        'active_shelters_count': active_shelters_count,
        'total_capacity': total_capacity,
        'total_occupancy': total_occupancy,
        'critical_shelters_count': critical_or_overcrowded_count,
        'overall_utilization': overall_utilization,
    }


def get_filtered_users(
    search: str = '',
    role_filter: str = '',
    status_filter: str = ''
) -> List[User]:
    """
    Queries users table with flexible filtering by search term (name/email),
    role, and active/inactive status.
    """
    query = User.query

    # 1. Text Search (Full Name or Email)
    search_clean = search.strip()
    if search_clean:
        search_pattern = f"%{search_clean}%"
        query = query.filter(
            or_(
                User.full_name.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )

    # 2. Role Filter
    if role_filter in VALID_ROLES:
        query = query.filter(User.role == role_filter)

    # 3. Status Filter
    if status_filter == 'active':
        query = query.filter(User.is_active.is_(True))
    elif status_filter == 'inactive':
        query = query.filter(User.is_active.is_(False))

    return query.order_by(User.id.asc()).all()


def get_shelters_overview() -> List[Dict[str, Any]]:
    """
    Returns a compact list of shelters with capacity and operational status
    formatted specifically for administrative overview.
    """
    shelters = Shelter.query.order_by(Shelter.name.asc()).all()
    overview = []

    for s in shelters:
        manager_name = s.manager.full_name if s.manager else 'Unassigned'
        overview.append({
            'id': s.id,
            'name': s.name,
            'address': s.address,
            'current_occupancy': s.current_occupancy,
            'max_capacity': s.max_capacity,
            'available_capacity': s.available_capacity,
            'occupancy_pct': s.occupancy_pct,
            'safe_capacity': s.safe_capacity,
            'status': s.status,
            'status_label': s.status_label,
            'capacity_status': s.capacity_status,
            'capacity_status_label': s.capacity_status_label,
            'capacity_badge_class': s.capacity_badge_class,
            'manager_name': manager_name,
            'managed_by': s.managed_by,
        })

    return overview


def toggle_user_active_status(user_id: int, current_admin_id: int) -> Tuple[bool, str]:
    """
    Toggles a user's active status.
    Safeguard: Admin cannot deactivate their own account.
    """
    user = User.query.get(user_id)
    if not user:
        return False, "User not found."

    # Self-Protection Guard
    if user.id == current_admin_id:
        return False, "Action Denied: You cannot deactivate your own administrator account."

    new_status = not user.is_active
    user.is_active = new_status
    user.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        state_str = "activated" if new_status else "deactivated"
        return True, f"User account '{user.full_name}' ({user.email}) has been {state_str}."
    except Exception as e:
        db.session.rollback()
        return False, f"Database error updating user status: {str(e)}"


def change_user_role(user_id: int, new_role: str, current_admin_id: int) -> Tuple[bool, str]:
    """
    Changes a user's role to any valid system role.
    Safeguard: Admin cannot revoke their own admin role.
    """
    user = User.query.get(user_id)
    if not user:
        return False, "User not found."

    if new_role not in VALID_ROLES:
        return False, f"Invalid role specified: '{new_role}'."

    # Self-Protection Guard
    if user.id == current_admin_id and new_role != 'admin':
        return False, "Action Denied: You cannot revoke your own administrator privileges."

    old_role_label = ROLE_LABELS.get(user.role, user.role)
    new_role_label = ROLE_LABELS.get(new_role, new_role)

    if user.role == new_role:
        return True, f"User '{user.full_name}' already holds the role of {new_role_label}."

    user.role = new_role
    user.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        return True, f"Updated role for '{user.full_name}' from {old_role_label} to {new_role_label}."
    except Exception as e:
        db.session.rollback()
        return False, f"Database error updating user role: {str(e)}"


def get_user_metadata(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves safe administrative metadata for a user.
    Password hashes and sensitive secrets are strictly omitted.
    """
    user = User.query.get(user_id)
    if not user:
        return None

    managed_shelters_list = [s.name for s in user.managed_shelters]
    submitted_requests_count = user.submitted_requests.count()

    return {
        'id': user.id,
        'full_name': user.full_name,
        'email': user.email,
        'role': user.role,
        'role_label': user.role_label,
        'is_active': user.is_active,
        'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if user.created_at else 'N/A',
        'updated_at': user.updated_at.strftime('%Y-%m-%d %H:%M:%S UTC') if user.updated_at else 'N/A',
        'managed_shelters': managed_shelters_list,
        'submitted_requests_count': submitted_requests_count,
    }


def get_system_configuration() -> Dict[str, Any]:
    """
    Collects real, active configuration values from the Flask app configuration.
    Provides transparency for administrators without introducing fake or unsafe settings.
    """
    cfg = current_app.config

    return {
        'safe_capacity_limit_pct': cfg.get('SAFE_OCCUPANCY_LIMIT_PCT', 85),
        'occupancy_thresholds': {
            'safe': cfg.get('OCCUPANCY_THRESHOLD_SAFE', 60.0),
            'moderate': cfg.get('OCCUPANCY_THRESHOLD_MODERATE', 80.0),
            'high': cfg.get('OCCUPANCY_THRESHOLD_HIGH', 95.0),
            'critical': cfg.get('OCCUPANCY_THRESHOLD_CRITICAL', 100.0),
        },
        'recommendation_weights': {
            'distance': cfg.get('WEIGHT_DISTANCE', 0.25),
            'capacity': cfg.get('WEIGHT_CAPACITY', 0.35),
            'facilities': cfg.get('WEIGHT_FACILITIES', 0.20),
            'resources': cfg.get('WEIGHT_RESOURCES', 0.20),
        },
        'predict_hours_ahead': cfg.get('PREDICT_HOURS_AHEAD', 6),
        'database_host': cfg.get('DB_HOST', 'localhost'),
        'database_port': cfg.get('DB_PORT', '3306'),
        'database_name': cfg.get('DB_NAME', 'shelter_system'),
        'session_cookie_httponly': cfg.get('SESSION_COOKIE_HTTPONLY', True),
        'session_cookie_samesite': cfg.get('SESSION_COOKIE_SAMESITE', 'Lax'),
        'session_lifetime_hours': int(cfg.get('PERMANENT_SESSION_LIFETIME').total_seconds() / 3600)
            if cfg.get('PERMANENT_SESSION_LIFETIME') else 12,
        'csrf_protection_active': True,
    }
