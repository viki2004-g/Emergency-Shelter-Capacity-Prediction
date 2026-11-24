"""
tests/test_admin.py — Automated Test Suite for System Administration & Governance.

Verifies:
  1. Role-Based Access Control (RBAC):
     - Admin access granted (200 OK)
     - Non-admin roles (citizen, shelter_manager, responder, authority) blocked with 403 Forbidden
     - Unauthenticated access redirected to /auth/login (302)
  2. Summary Statistics & Metrics accuracy
  3. User Filtering & Search:
     - Text search by name and email
     - Role-based filtering
     - Status-based filtering (active / inactive)
  4. Administrative Governance Actions:
     - Account deactivation & reactivation
     - Role modification
     - Admin self-protection (deactivation prevented)
     - Admin self-protection (demotion prevented)
     - Non-admin blocked from executing administrative POST actions (403)
  5. Information Security:
     - Sanitized JSON detail endpoint
     - Zero leakage of password hashes or credentials in HTML responses
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models.user import User
from services.admin import (
    get_admin_dashboard_stats,
    get_filtered_users,
    get_shelters_overview,
    toggle_user_active_status,
    change_user_role,
    get_user_metadata,
    get_system_configuration,
)

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


def run_admin_tests():
    global PASS, FAIL
    app = create_app()
    client = app.test_client()

    print("\n=================================================================")
    print("Suite 1: RBAC & Access Control for Admin Portal")
    print("=================================================================")

    # 1. Unauthenticated access
    res = client.get('/admin/')
    check("Unauthenticated access to /admin/ redirects (302)", res.status_code == 302)
    check("Redirects to login page", '/auth/login' in res.headers.get('Location', ''))

    # 2. Citizen access
    client.post('/auth/login', data={'email': 'citizen@example.com', 'password': 'Password@123'}, follow_redirects=True)
    res = client.get('/admin/')
    check("Citizen access to /admin/ returns 403 Forbidden", res.status_code == 403)
    client.get('/auth/logout')

    # 3. Shelter Manager access
    client.post('/auth/login', data={'email': 'manager1@shelter.gov', 'password': 'Password@123'}, follow_redirects=True)
    res = client.get('/admin/')
    check("Shelter Manager access to /admin/ returns 403 Forbidden", res.status_code == 403)
    client.get('/auth/logout')

    # 4. Responder access
    client.post('/auth/login', data={'email': 'responder1@shelter.gov', 'password': 'Password@123'}, follow_redirects=True)
    res = client.get('/admin/')
    check("Responder access to /admin/ returns 403 Forbidden", res.status_code == 403)
    client.get('/auth/logout')

    # 5. Authority access
    client.post('/auth/login', data={'email': 'authority@shelter.gov', 'password': 'Password@123'}, follow_redirects=True)
    res = client.get('/admin/')
    check("Authority access to /admin/ returns 403 Forbidden", res.status_code == 403)
    client.get('/auth/logout')

    # 6. Admin access
    client.post('/auth/login', data={'email': 'admin@shelter.gov', 'password': 'Password@123'}, follow_redirects=True)
    res = client.get('/admin/')
    check("Admin access to /admin/ returns 200 OK", res.status_code == 200)

    html = res.get_data(as_text=True)
    check("Admin dashboard title present", "System Administration & Governance" in html)
    check("User Governance tab present", "User Governance & RBAC" in html)
    check("Shelter Capacity tab present", "Shelter Capacity Overview" in html)
    check("System Configuration tab present", "System Configuration" in html)

    print("\n=================================================================")
    print("Suite 2: Admin Dashboard Summary Statistics")
    print("=================================================================")
    with app.app_context():
        stats = get_admin_dashboard_stats()
        check("Total users count is positive integer", stats['total_users'] > 0)
        check("Active users + inactive users equals total users",
              stats['active_users'] + stats['inactive_users'] == stats['total_users'])
        check("Users by role includes all valid roles",
              all(r in stats['users_by_role'] for r in ('admin', 'authority', 'responder', 'shelter_manager', 'citizen')))
        check("Total shelters count is positive integer", stats['total_shelters'] > 0)
        check("Active shelters count is positive integer", stats['active_shelters_count'] > 0)
        check("Overall utilization percentage is calculated", stats['overall_utilization'] >= 0.0)

    print("\n=================================================================")
    print("Suite 3: User Filtering & Search Services")
    print("=================================================================")
    with app.app_context():
        # Search by name
        results = get_filtered_users(search='Amit')
        check("Search by name returns matching user", any(u.full_name == 'Amit Kulkarni' for u in results))
        check("Search by name excludes non-matching user", all('Amit' in u.full_name or 'amit' in u.email.lower() for u in results))

        # Search by email
        results = get_filtered_users(search='responder1@')
        check("Search by email returns matching user", len(results) == 1 and results[0].email == 'responder1@shelter.gov')

        # Filter by role
        results = get_filtered_users(role_filter='responder')
        check("Role filter returns only responders", all(u.role == 'responder' for u in results) and len(results) > 0)

        # Filter by status
        results = get_filtered_users(status_filter='inactive')
        check("Status filter returns inactive users", all(not u.is_active for u in results))

    print("\n=================================================================")
    print("Suite 4: User Management Actions & Self-Protection Guards")
    print("=================================================================")
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
        admin_id = admin.id
        target = User.query.filter(User.role == 'citizen', User.id != admin_id).first()
        target_id = target.id
        initial_status = target.is_active

        # 1. Admin toggles target user status
        ok, msg = toggle_user_active_status(target_id, admin_id)
        check("Status toggle succeeds for another user", ok)
        check("User status was inverted", target.is_active != initial_status)

        # Revert status
        ok, msg = toggle_user_active_status(target_id, admin_id)
        check("Status revert succeeds", ok and target.is_active == initial_status)

        # 2. Admin self-deactivation guard
        ok, msg = toggle_user_active_status(admin_id, admin_id)
        check("Admin self-deactivation is strictly rejected", not ok)
        check("Rejection message explains self-protection", "cannot deactivate your own" in msg)
        check("Admin account remains active", admin.is_active is True)

        # 3. Admin changes role for target user
        initial_role = target.role
        ok, msg = change_user_role(target_id, 'responder', admin_id)
        check("Role modification succeeds for citizen -> responder", ok)
        check("Target user role is now responder", target.role == 'responder')

        # Revert role
        ok, msg = change_user_role(target_id, initial_role, admin_id)
        check("Role modification revert succeeds", ok and target.role == initial_role)

        # 4. Admin self-demotion guard
        ok, msg = change_user_role(admin_id, 'citizen', admin_id)
        check("Admin self-demotion is strictly rejected", not ok)
        check("Rejection message explains privilege protection", "cannot revoke your own" in msg)
        check("Admin role remains admin", admin.role == 'admin')

    # Test HTTP POST action endpoints
    post_res = client.post(f'/admin/users/{admin_id}/toggle-status', follow_redirects=True)
    post_html = post_res.get_data(as_text=True)
    check("HTTP POST self-deactivation returns error flash", "cannot deactivate your own" in post_html or "Action Denied" in post_html)

    post_res = client.post(f'/admin/users/{admin_id}/change-role', data={'new_role': 'citizen'}, follow_redirects=True)
    post_html = post_res.get_data(as_text=True)
    check("HTTP POST self-demotion returns error flash", "cannot revoke your own" in post_html or "Action Denied" in post_html)

    print("\n=================================================================")
    print("Suite 5: Non-Admin Protection for Administrative Endpoints")
    print("=================================================================")
    client.get('/auth/logout')
    # Login as citizen
    client.post('/auth/login', data={'email': 'citizen@example.com', 'password': 'Password@123'}, follow_redirects=True)
    res = client.post(f'/admin/users/{admin_id}/toggle-status')
    check("Citizen cannot execute toggle-status (403)", res.status_code == 403)

    res = client.post(f'/admin/users/{admin_id}/change-role', data={'new_role': 'admin'})
    check("Citizen cannot execute change-role (403)", res.status_code == 403)

    res = client.get(f'/admin/users/{admin_id}/detail')
    check("Citizen cannot access user detail JSON (403)", res.status_code == 403)
    client.get('/auth/logout')

    print("\n=================================================================")
    print("Suite 6: Information Disclosure Prevention & Sanitation")
    print("=================================================================")
    # Login back as admin
    client.post('/auth/login', data={'email': 'admin@shelter.gov', 'password': 'Password@123'}, follow_redirects=True)
    res = client.get(f'/admin/users/{admin_id}/detail')
    check("Admin detail JSON endpoint returns 200", res.status_code == 200)
    data = res.get_json()
    check("JSON metadata does not leak password_hash", 'password_hash' not in data)
    check("JSON metadata does not leak password", 'password' not in data)
    check("JSON metadata includes full_name and email", data.get('email') == 'admin@shelter.gov')

    page = client.get('/admin/')
    html = page.get_data(as_text=True)
    check("HTML response does not leak password hashes ($2b$)", "$2b$" not in html)
    check("HTML response does not leak secrets", "SECRET_KEY" not in html)

    print("\n=================================================================")
    print(f"ADMIN TEST SUITE SUMMARY: {PASS} passed, {FAIL} failed")
    print("=================================================================")
    return FAIL == 0


if __name__ == '__main__':
    success = run_admin_tests()
    sys.exit(0 if success else 1)
