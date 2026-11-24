"""
tests/test_dashboard.py — Comprehensive test suite for the Emergency Management Dashboard.

Validates:
  Suite 1: Data Integrity & Core Metrics Calculation (get_dashboard_summary)
  Suite 2: Chart.js Payload Integrity (horizontal bar & capacity doughnut)
  Suite 3: Shelter List Item Classification Integrity
  Suite 4: Role-Aware & Filter Behavior (all, critical, overcrowded, overload_risk, shortage, my_shelters)
  Suite 5: HTTP Endpoints, Authentication & RBAC
  Suite 6: Alert Resolution Lifecycle & Access Control

Run:
  venv\\Scripts\\python.exe -X utf8 tests/test_dashboard.py
"""

import os
import sys
import json
from datetime import datetime

# Ensure shelter_system is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db, bcrypt
from models.shelter import Shelter
from models.request import ShelterRequest
from models.allocation import Allocation
from models.occupancy import OccupancyHistory
from models.alert import Alert
from models.facility import ShelterFacility
from models.resource import Resource
from models.user import User

from services.dashboard import get_dashboard_summary

app = create_app('testing')

total_tests = 0
passed_tests = 0


def record(name: str, passed: bool, detail: str = ""):
    global total_tests, passed_tests
    total_tests += 1
    if passed:
        passed_tests += 1
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} -> {detail}")


def run_tests():
    print("\n" + "=" * 75)
    print("EMERGENCY MANAGEMENT DASHBOARD TEST SUITE")
    print("=" * 75)

    with app.app_context():
        # Setup test accounts
        admin_email = "dash_admin@test.local"
        manager_email = "dash_mgr@test.local"
        resp_email = "dash_resp@test.local"

        admin_user = User.query.filter_by(email=admin_email).first()
        if not admin_user:
            admin_user = User(
                email=admin_email,
                full_name="Dashboard Commander Admin",
                role="authority",
                password_hash=bcrypt.generate_password_hash("Password@123").decode('utf-8'),
                is_active=True
            )
            db.session.add(admin_user)

        # Get an active shelter for manager assignment
        sample_shelter = Shelter.query.filter_by(status='active').first()

        manager_user = User.query.filter_by(email=manager_email).first()
        if not manager_user:
            manager_user = User(
                email=manager_email,
                full_name="Dashboard Shelter Manager",
                role="shelter_manager",
                password_hash=bcrypt.generate_password_hash("Password@123").decode('utf-8'),
                is_active=True
            )
            db.session.add(manager_user)
            db.session.flush()

        if sample_shelter:
            sample_shelter.managed_by = manager_user.id

        responder_user = User.query.filter_by(email=resp_email).first()
        if not responder_user:
            responder_user = User(
                email=resp_email,
                full_name="Dashboard Field Responder",
                role="responder",
                password_hash=bcrypt.generate_password_hash("Password@123").decode('utf-8'),
                is_active=True
            )
            db.session.add(responder_user)

        db.session.commit()

        # =========================================================================
        # SUITE 1: Data Integrity & Core Metrics Calculation
        # =========================================================================
        print("\n--- Suite 1: Data Integrity & Core Metrics Calculation ---")
        summary = get_dashboard_summary(admin_user, hours_ahead=6)

        record("Summary returns dict with all core keys",
               isinstance(summary, dict) and all(k in summary for k in [
                   'total_shelters', 'active_shelters', 'inactive_shelters',
                   'total_capacity', 'total_occupancy', 'total_safe_capacity',
                   'global_occupancy_pct', 'net_safe_available', 'usable_safe_available',
                   'critical_shelters_count', 'overcrowded_shelters_count',
                   'predicted_overloads_count', 'resource_shortages_count',
                   'shelters_data', 'unresolved_alerts', 'recent_allocations', 'recent_requests',
                   'chart_shelter_load', 'chart_capacity_doughnut'
               ]))

        record("Total shelters is non-negative int", isinstance(summary['total_shelters'], int) and summary['total_shelters'] >= 0)
        record("Active shelters <= total shelters", summary['active_shelters'] <= summary['total_shelters'])
        record("Inactive shelters = total - active", summary['inactive_shelters'] == summary['total_shelters'] - summary['active_shelters'])
        record("Total capacity is non-negative int", isinstance(summary['total_capacity'], int) and summary['total_capacity'] >= 0)
        record("Current occupancy is non-negative int", isinstance(summary['total_occupancy'], int) and summary['total_occupancy'] >= 0)
        record("Occupancy percentage is valid float", isinstance(summary['global_occupancy_pct'], float) and summary['global_occupancy_pct'] >= 0.0)
        record("Safe available headroom calculated", isinstance(summary['usable_safe_available'], int) and summary['usable_safe_available'] >= 0)
        record("Safe planning limit calculated", isinstance(summary['total_safe_capacity'], int) and summary['total_safe_capacity'] >= 0)
        record("Critical shelters count is int >= 0", isinstance(summary['critical_shelters_count'], int) and summary['critical_shelters_count'] >= 0)
        record("Overcrowded shelters count is int >= 0", isinstance(summary['overcrowded_shelters_count'], int) and summary['overcrowded_shelters_count'] >= 0)
        record("Predicted overloads count is int >= 0", isinstance(summary['predicted_overloads_count'], int) and summary['predicted_overloads_count'] >= 0)
        record("Resource shortages count is int >= 0", isinstance(summary['resource_shortages_count'], int) and summary['resource_shortages_count'] >= 0)
        record("Alerts count matches list length", summary['unresolved_alerts_count'] == len(summary['unresolved_alerts']))

        # =========================================================================
        # SUITE 2: Chart.js Payload Integrity
        # =========================================================================
        print("\n--- Suite 2: Chart.js Payload Integrity ---")
        chart_load = summary['chart_shelter_load']
        record("Load chart has labels list", isinstance(chart_load.get('labels'), list))
        record("Load chart has occupancies list", isinstance(chart_load.get('occupancies'), list))
        record("Load chart has safe_capacities list", isinstance(chart_load.get('safe_capacities'), list))
        record("Load chart has max_capacities list", isinstance(chart_load.get('max_capacities'), list))
        record("Load chart has bar_colors list", isinstance(chart_load.get('bar_colors'), list))
        n_bars = len(chart_load['labels'])
        record("Load chart array lengths match label count",
               len(chart_load['occupancies']) == n_bars and
               len(chart_load['safe_capacities']) == n_bars and
               len(chart_load['max_capacities']) == n_bars and
               len(chart_load['bar_colors']) == n_bars)

        chart_cap = summary['chart_capacity_doughnut']
        record("Capacity doughnut has 3 segment labels",
               isinstance(chart_cap.get('labels'), list) and len(chart_cap['labels']) == 3)
        record("Capacity doughnut data has 3 data values",
               isinstance(chart_cap.get('data'), list) and len(chart_cap['data']) == 3)
        record("Capacity doughnut values are non-negative",
               all(v >= 0 for v in chart_cap['data']))

        # =========================================================================
        # SUITE 3: Shelter List Item Classification Integrity
        # =========================================================================
        print("\n--- Suite 3: Shelter List Item Classification Integrity ---")
        shelters_list = summary['shelters_data']
        record("Shelters list populated", len(shelters_list) > 0)

        if shelters_list:
            first = shelters_list[0]
            record("Shelter item has required evaluation fields",
                   hasattr(first['shelter'], 'id') and all(k in first for k in [
                       'safe_capacity', 'safe_available_capacity', 'occupancy_pct',
                       'capacity_status', 'capacity_badge_class', 'prediction',
                       'has_shortage', 'shortage_fields'
                   ]))
            record("Capacity status is valid classification",
                   first['capacity_status'] in ['safe', 'moderate', 'high', 'critical', 'overcrowded', 'inactive'])
            record("Prediction dictionary has overload_risk field",
                   'overload_risk' in first['prediction'])

        # Check shortage calculation logic on real data
        shortage_count_in_items = sum(1 for item in shelters_list if item['has_shortage'])
        record("Summary shortage metric matches flagged shelters count",
               summary['resource_shortages_count'] == shortage_count_in_items)

        # =========================================================================
        # SUITE 4: Role-Aware & Filter Behavior
        # =========================================================================
        print("\n--- Suite 4: Role-Aware & Filter Behavior ---")
        # Shelter Manager scoped view
        mgr_summary = get_dashboard_summary(manager_user, hours_ahead=6)
        record("Manager summary identifies manager role", mgr_summary['is_manager'] is True)
        record("Manager summary includes my_shelters list",
               isinstance(mgr_summary.get('my_shelters'), list) and len(mgr_summary['my_shelters']) >= 1)
        record("my_shelters item matches assigned manager ID",
               mgr_summary['my_shelters'][0]['managed_by'] == manager_user.id)

        # Filter 'critical'
        record("Critical shelters count matches filtered list length",
               summary['critical_shelters_count'] == len(summary['critical_shelters']))
        record("All critical items have critical status or safe headroom breach",
               all(s['capacity_status'] in ['critical', 'overcrowded'] or s['safe_available_capacity'] <= 0 or s['status'] in ('full', 'damaged') for s in summary['critical_shelters']))

        # Filter 'overload_risk'
        record("Predicted overloads count matches list length",
               summary['predicted_overloads_count'] == len(summary['predicted_overloads']))
        record("All overload items have high or critical overload predictions",
               all(s['prediction'].get('overload_risk') in ['high', 'critical'] for s in summary['predicted_overloads']))

        # Filter 'shortage'
        record("Resource shortages count matches list length",
               summary['resource_shortages_count'] == len(summary['resource_shortages']))
        record("All shortage items have has_shortage True",
               all(s['has_shortage'] for s in summary['resource_shortages']))

        # =========================================================================
        # SUITE 5: HTTP Endpoints & Authentication
        # =========================================================================
        print("\n--- Suite 5: HTTP Endpoints & Authentication ---")
        client = app.test_client()

        # Unauthenticated access
        r_unauth_dash = client.get('/dashboard/')
        record("Unauthenticated GET /dashboard/ -> 302 redirect", r_unauth_dash.status_code == 302)
        record("Unauthenticated GET /dashboard/ redirects to /auth/login",
               '/auth/login' in r_unauth_dash.headers.get('Location', ''))

        r_unauth_api = client.get('/dashboard/api/stats')
        record("Unauthenticated GET /dashboard/api/stats -> 302 redirect", r_unauth_api.status_code == 302)

        # Public Home page unauthenticated -> 200 with operational metrics
        r_home = client.get('/')
        record("Unauthenticated GET / returns 200 OK", r_home.status_code == 200)
        home_html = r_home.data.decode('utf-8', errors='replace')
        record("Home page displays emergency incident portal",
               "Emergency Shelter Capacity" in home_html and "Authorized Portal Access" in home_html)

        # Admin login and access
        client.post('/auth/login', data={'email': admin_email, 'password': 'Password@123'})
        r_home_auth = client.get('/')
        record("Authenticated GET / redirects to /dashboard/",
               r_home_auth.status_code == 302 and '/dashboard/' in r_home_auth.headers.get('Location', ''))

        r_dash = client.get('/dashboard/')
        record("Authenticated GET /dashboard/ returns 200 OK", r_dash.status_code == 200)
        dash_html = r_dash.data.decode('utf-8', errors='replace')
        record("Dashboard contains Incident Command Top Bar", "Emergency Shelter Operations" in dash_html)
        record("Dashboard contains Chart.js canvas elements",
               'id="shelterLoadChart"' in dash_html and 'id="capacityDoughnutChart"' in dash_html)
        record("Dashboard contains filter tabs",
               "All Shelters (" in dash_html and "Critical (" in dash_html and "Overload Risk (" in dash_html)
        record("Dashboard contains recent activity sections",
               "Recent Confirmed Allocations" in dash_html and "Recent Shelter Requests" in dash_html)

        # Filtered views via HTTP
        r_crit_http = client.get('/dashboard/?filter=critical')
        record("GET /dashboard/?filter=critical returns 200 OK", r_crit_http.status_code == 200)

        r_risk_http = client.get('/dashboard/?filter=overload_risk')
        record("GET /dashboard/?filter=overload_risk returns 200 OK", r_risk_http.status_code == 200)

        r_short_http = client.get('/dashboard/?filter=shortage')
        record("GET /dashboard/?filter=shortage returns 200 OK", r_short_http.status_code == 200)

        # API Stats endpoint
        r_api = client.get('/dashboard/api/stats')
        record("Authenticated GET /dashboard/api/stats returns 200 OK", r_api.status_code == 200)
        api_data = json.loads(r_api.data.decode('utf-8'))
        record("API stats JSON contains core metrics",
               all(k in api_data for k in ['total_shelters', 'active_shelters', 'total_capacity', 'total_occupancy']))

        # =========================================================================
        # SUITE 6: Alert Resolution Lifecycle & RBAC
        # =========================================================================
        print("\n--- Suite 6: Alert Resolution Lifecycle & RBAC ---")
        # Create a dedicated test alert
        test_alert = Alert(
            shelter_id=sample_shelter.id if sample_shelter else 1,
            alert_type='critical_capacity',
            severity='critical',
            message='Automated Dashboard Test Alert',
            is_resolved=False
        )
        db.session.add(test_alert)
        db.session.commit()
        alert_id = test_alert.id

        # Non-authority (Responder) attempts to resolve -> 403 Forbidden
        client.get('/auth/logout')  # Clean session
        client_resp = app.test_client()
        client_resp.get('/auth/logout')
        resp_login_res = client_resp.post('/auth/login', data={'email': resp_email, 'password': 'Password@123'}, follow_redirects=True)
        with client_resp:
            r_resolve_resp = client_resp.post(f'/dashboard/alerts/{alert_id}/resolve')
        record("Responder POST /dashboard/alerts/<id>/resolve returns 403 Forbidden",
               r_resolve_resp.status_code == 403,
               f"Got status {r_resolve_resp.status_code}, location={r_resolve_resp.headers.get('Location')}")

        db.session.refresh(test_alert)
        record("Alert remains unresolved after unauthorized attempt", test_alert.is_resolved is False)

        # Authority resolves alert -> 302 redirect with success
        client_resp.get('/auth/logout')
        client_auth = app.test_client()
        client_auth.get('/auth/logout')
        auth_login_res = client_auth.post('/auth/login', data={'email': admin_email, 'password': 'Password@123'}, follow_redirects=True)
        r_resolve_auth = client_auth.post(f'/dashboard/alerts/{alert_id}/resolve', follow_redirects=True)
        record("Authority POST /dashboard/alerts/<id>/resolve succeeds (200 after redirect)",
               r_resolve_auth.status_code == 200,
               f"auth_login={auth_login_res.status_code}, resolve={r_resolve_auth.status_code}")

        db.session.refresh(test_alert)
        record("Alert is now resolved in database", test_alert.is_resolved is True)
        record("Alert resolved_by matches admin user id", test_alert.resolved_by == admin_user.id)
        record("Alert resolved_at timestamp is set", test_alert.resolved_at is not None)

        # Resolving non-existent alert -> 404
        r_resolve_404 = client_auth.post('/dashboard/alerts/999999/resolve')
        record("Resolving non-existent alert returns 404", r_resolve_404.status_code == 404)

        # Cleanup test alert
        db.session.delete(test_alert)
        db.session.commit()

    # Summary
    print("\n" + "=" * 75)
    print(f"RESULTS: {passed_tests} / {total_tests} tests passed.")
    print("=" * 75)
    if passed_tests < total_tests:
        sys.exit(1)


if __name__ == '__main__':
    run_tests()
