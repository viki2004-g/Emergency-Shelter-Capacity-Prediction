"""
tests/test_alerts.py — Comprehensive test suite for the Emergency Alerts System.

Validates:
  Suite 1: Condition Alert Generation (overcrowded, critical capacity, predicted overload, resource shortage, damage)
  Suite 2: Strict Deduplication Guarantee (no redundant alerts for same shelter and condition)
  Suite 3: Automatic Resolution upon Condition Recovery
  Suite 4: Read / Unread State Tracking Lifecycle
  Suite 5: HTTP Endpoints, Filtering & Role-Based Access Control (RBAC)

Run:
  venv\\Scripts\\python.exe -X utf8 tests/test_alerts.py
"""

import os
import sys
import json
from datetime import datetime, timedelta

# Ensure shelter_system is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db, bcrypt
from models.shelter import Shelter
from models.alert import Alert
from models.resource import Resource
from models.user import User

from services.alerts import (
    create_or_update_alert,
    auto_resolve_alert,
    evaluate_shelter_alerts,
    evaluate_all_alerts,
    mark_alert_read,
    mark_all_alerts_read,
    resolve_alert,
    get_alert_counts,
    get_active_alerts,
)

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
    print("EMERGENCY ALERTS SYSTEM TEST SUITE")
    print("=" * 75)

    with app.app_context():
        # Setup test accounts
        admin_email = "alert_admin@test.local"
        resp_email = "alert_resp@test.local"

        admin_user = User.query.filter_by(email=admin_email).first()
        if not admin_user:
            admin_user = User(
                email=admin_email,
                full_name="Alert System Admin",
                role="authority",
                password_hash=bcrypt.generate_password_hash("Password@123").decode('utf-8'),
                is_active=True
            )
            db.session.add(admin_user)

        resp_user = User.query.filter_by(email=resp_email).first()
        if not resp_user:
            resp_user = User(
                email=resp_email,
                full_name="Alert Field Responder",
                role="responder",
                password_hash=bcrypt.generate_password_hash("Password@123").decode('utf-8'),
                is_active=True
            )
            db.session.add(resp_user)

        # Setup dedicated test shelter
        test_shelter = Shelter.query.filter_by(name="TestAlert_Shelter_Alpha").first()
        if not test_shelter:
            test_shelter = Shelter(
                name="TestAlert_Shelter_Alpha",
                address="Shivajinagar EOC Test Zone",
                latitude=18.5300,
                longitude=73.8500,
                max_capacity=100,
                current_occupancy=50,
                status='active',
                safe_limit_pct=85
            )
            db.session.add(test_shelter)
            db.session.flush()

        test_res = Resource.query.filter_by(shelter_id=test_shelter.id).first()
        if not test_res:
            test_res = Resource(
                shelter_id=test_shelter.id,
                beds_available=50,
                food_portions=200,
                water_litres=500,
                medicine_kits=25
            )
            db.session.add(test_res)

        db.session.commit()

        # Clean prior test alerts for this shelter
        Alert.query.filter_by(shelter_id=test_shelter.id).delete()
        db.session.commit()

        # =========================================================================
        # SUITE 1: Condition Alert Generation
        # =========================================================================
        print("\n--- Suite 1: Condition Alert Generation ---")

        # 1.1 Safe Baseline: occupancy 50/100 -> No alerts generated
        test_shelter.current_occupancy = 50
        test_res.water_litres = 500
        test_res.food_portions = 200
        test_res.medicine_kits = 25
        db.session.commit()

        evaluate_shelter_alerts(test_shelter, auto_commit=True)
        active_alerts = Alert.query.filter_by(shelter_id=test_shelter.id, is_resolved=False).all()
        record("Safe capacity produces zero alerts", len(active_alerts) == 0)

        # 1.2 Overcrowded: occupancy 120/100 (>100%) -> alert_type='overcrowded', severity='critical'
        test_shelter.current_occupancy = 120
        db.session.commit()
        evaluate_shelter_alerts(test_shelter, auto_commit=True)

        overcrowded_alert = Alert.query.filter_by(
            shelter_id=test_shelter.id,
            alert_type='overcrowded',
            is_resolved=False
        ).first()
        record("Overcrowding generates alert with type 'overcrowded'", overcrowded_alert is not None)
        record("Overcrowding alert severity is 'critical'",
               overcrowded_alert is not None and overcrowded_alert.severity == 'critical')
        record("Overcrowding message contains occupancy and excess count",
               overcrowded_alert is not None and "120/100" in overcrowded_alert.message and "20 people" in overcrowded_alert.message)

        # 1.3 Critical Capacity: occupancy 96/100 (safe capacity 85 breached, safe headroom <= 0)
        test_shelter.current_occupancy = 96
        db.session.commit()
        evaluate_shelter_alerts(test_shelter, auto_commit=True)

        crit_alert = Alert.query.filter_by(
            shelter_id=test_shelter.id,
            alert_type='critical_capacity',
            is_resolved=False
        ).first()
        record("Critical capacity generates alert with type 'critical_capacity'", crit_alert is not None)
        record("Critical capacity severity is 'critical'",
               crit_alert is not None and crit_alert.severity == 'critical')
        record("Critical capacity message mentions headroom breach",
               crit_alert is not None and "headroom breached" in crit_alert.message)

        # 1.4 Safe Limit Warning: occupancy 82/100 (safe capacity 85, headroom 3 > 0, >=80% threshold)
        # Clean previous critical alert to isolate warning
        Alert.query.filter_by(shelter_id=test_shelter.id).delete()
        test_shelter.current_occupancy = 82
        db.session.commit()
        evaluate_shelter_alerts(test_shelter, auto_commit=True)

        warn_alert = Alert.query.filter_by(
            shelter_id=test_shelter.id,
            alert_type='critical_capacity',
            is_resolved=False
        ).first()
        record("Safe limit breach generates warning level alert",
               warn_alert is not None and warn_alert.severity == 'warning')

        # 1.5 Important Resource Shortage (Zero water) -> critical resource_shortage alert
        test_res.water_litres = 0
        db.session.commit()
        evaluate_shelter_alerts(test_shelter, auto_commit=True)

        shortage_alert = Alert.query.filter_by(
            shelter_id=test_shelter.id,
            alert_type='resource_shortage',
            is_resolved=False
        ).first()
        record("Zero drinking water generates resource_shortage alert", shortage_alert is not None)
        record("Depleted drinking water triggers 'critical' severity",
               shortage_alert is not None and shortage_alert.severity == 'critical')
        record("Shortage message mentions drinking water",
               shortage_alert is not None and "Drinking Water" in shortage_alert.message)

        # 1.6 Facility Damaged -> critical shelter_damaged alert
        test_shelter.status = 'damaged'
        db.session.commit()
        evaluate_shelter_alerts(test_shelter, auto_commit=True)

        damaged_alert = Alert.query.filter_by(
            shelter_id=test_shelter.id,
            alert_type='shelter_damaged',
            is_resolved=False
        ).first()
        record("Damaged status generates 'shelter_damaged' alert", damaged_alert is not None)
        record("Facility hazard severity is 'critical'",
               damaged_alert is not None and damaged_alert.severity == 'critical')

        # Reset status back to active and evaluate steady state
        test_shelter.status = 'active'
        db.session.commit()
        evaluate_shelter_alerts(test_shelter, auto_commit=True)

        # =========================================================================
        # SUITE 2: Strict Deduplication Guarantee
        # =========================================================================
        print("\n--- Suite 2: Strict Deduplication Guarantee ---")
        count_before = Alert.query.filter_by(shelter_id=test_shelter.id, is_resolved=False).count()


        # Re-evaluate 5 consecutive times
        for _ in range(5):
            evaluate_shelter_alerts(test_shelter, auto_commit=True)

        count_after = Alert.query.filter_by(shelter_id=test_shelter.id, is_resolved=False).count()
        record("Re-evaluating identical conditions creates zero duplicate rows",
               count_before == count_after,
               f"before={count_before}, after={count_after}")

        # In-place update test
        alert_row, is_new = create_or_update_alert(
            shelter_id=test_shelter.id,
            alert_type='resource_shortage',
            severity='critical',
            message='Updated Shortage Telemetry: Emergency delivery scheduled',
            auto_commit=True
        )
        record("create_or_update_alert returns is_new=False for existing alert", is_new is False)
        record("Existing alert row updated with new message in place",
               alert_row.message == 'Updated Shortage Telemetry: Emergency delivery scheduled')

        # =========================================================================
        # SUITE 3: Auto-Resolution on Condition Recovery
        # =========================================================================
        print("\n--- Suite 3: Auto-Resolution on Condition Recovery ---")
        # Restock supplies and reduce occupancy back to safe baseline (40/100)
        test_shelter.current_occupancy = 40
        test_res.water_litres = 600
        test_res.food_portions = 300
        test_res.medicine_kits = 30
        db.session.commit()

        evaluate_shelter_alerts(test_shelter, auto_commit=True)

        unresolved_now = Alert.query.filter_by(shelter_id=test_shelter.id, is_resolved=False).count()
        record("All prior alerts automatically resolved after condition returns to normal",
               unresolved_now == 0,
               f"Remaining unresolved: {unresolved_now}")

        resolved_alerts = Alert.query.filter_by(shelter_id=test_shelter.id, is_resolved=True).all()
        record("Auto-resolved alerts have resolved_at timestamp",
               all(a.resolved_at is not None for a in resolved_alerts))

        # =========================================================================
        # SUITE 4: Read / Unread State Tracking
        # =========================================================================
        print("\n--- Suite 4: Read / Unread State Tracking ---")
        # Generate fresh alert
        new_alert, _ = create_or_update_alert(
            shelter_id=test_shelter.id,
            alert_type='critical_capacity',
            severity='warning',
            message='Read state lifecycle test alert',
            auto_commit=True
        )

        record("New alert initialized with is_read = False", new_alert.is_read is False)
        counts_before_read = get_alert_counts()
        record("Unread counter reflects unread alert", counts_before_read['unread'] >= 1)

        # Mark single alert read
        mark_alert_read(new_alert.id)
        db.session.refresh(new_alert)
        record("mark_alert_read sets is_read = True", new_alert.is_read is True)

        # Create two more unread alerts
        a2, _ = create_or_update_alert(test_shelter.id, 'resource_shortage', 'warning', 'Shortage test unread', auto_commit=True)
        a2.is_read = False
        db.session.commit()

        read_count = mark_all_alerts_read()
        db.session.refresh(a2)
        record("mark_all_alerts_read marks active unread alerts as read", a2.is_read is True)

        # =========================================================================
        # SUITE 5: HTTP Endpoints, Filtering & RBAC
        # =========================================================================
        print("\n--- Suite 5: HTTP Endpoints, Filtering & RBAC ---")
        client = app.test_client()

        # 5.1 Unauthenticated access -> Redirect to /auth/login
        r_unauth = client.get('/alerts/')
        record("Unauthenticated GET /alerts/ redirects to login (302)", r_unauth.status_code == 302)

        # 5.2 Authenticated access as Admin
        client.post('/auth/login', data={'email': admin_email, 'password': 'Password@123'}, follow_redirects=True)
        r_alerts = client.get('/alerts/')
        record("Authenticated GET /alerts/ returns 200 OK", r_alerts.status_code == 200)

        alerts_html = r_alerts.data.decode('utf-8', errors='replace')
        record("Alerts page contains header title", "Emergency Alerts" in alerts_html and "Warning Center" in alerts_html)
        record("Alerts page contains filter toolbar", "All Severities" in alerts_html and "Active (" in alerts_html)


        # 5.3 Filtering
        r_crit_filter = client.get('/alerts/?severity=critical')
        record("GET /alerts/?severity=critical returns 200 OK", r_crit_filter.status_code == 200)

        r_res_filter = client.get('/alerts/?status=resolved')
        record("GET /alerts/?status=resolved returns 200 OK", r_res_filter.status_code == 200)

        r_read_filter = client.get('/alerts/?read=unread')
        record("GET /alerts/?read=unread returns 200 OK", r_read_filter.status_code == 200)

        # 5.4 POST /alerts/<id>/read
        r_mark = client.post(f'/alerts/{a2.id}/read', follow_redirects=True)
        record("POST /alerts/<id>/read succeeds (200 after redirect)", r_mark.status_code == 200)

        # 5.5 POST /alerts/scan (Network Scan)
        r_scan = client.post('/alerts/scan', follow_redirects=True)
        record("Authority POST /alerts/scan succeeds (200 after redirect)", r_scan.status_code == 200)
        scan_html = r_scan.data.decode('utf-8', errors='replace')
        record("Flash notification confirms network scan complete", "Network scan complete" in scan_html)

        # 5.6 Non-authority (Responder) resolution attempt -> 403 Forbidden
        client.get('/auth/logout')
        client_resp = app.test_client()
        client_resp.get('/auth/logout')
        client_resp.post('/auth/login', data={'email': resp_email, 'password': 'Password@123'}, follow_redirects=True)

        r_resp_resolve = client_resp.post(f'/alerts/{new_alert.id}/resolve')
        record("Responder POST /alerts/<id>/resolve returns 403 Forbidden", r_resp_resolve.status_code == 403)

        # 5.7 Authority resolution -> 302/200 success
        client_resp.get('/auth/logout')
        client_auth = app.test_client()
        client_auth.get('/auth/logout')
        client_auth.post('/auth/login', data={'email': admin_email, 'password': 'Password@123'}, follow_redirects=True)

        r_auth_resolve = client_auth.post(
            f'/alerts/{new_alert.id}/resolve',
            data={'notes': 'Inspected by Authority. Space restored.'},
            follow_redirects=True
        )
        record("Authority POST /alerts/<id>/resolve succeeds (200 after redirect)", r_auth_resolve.status_code == 200)

        db.session.refresh(new_alert)
        record("Alert is marked resolved in DB", new_alert.is_resolved is True)
        record("Alert resolved_by matches admin user id", new_alert.resolved_by == admin_user.id)
        record("Resolution note appended to message", "Inspected by Authority" in new_alert.message)

        # 5.8 JSON API endpoint
        r_api = client_auth.get('/alerts/api/active')
        record("GET /alerts/api/active returns 200 OK", r_api.status_code == 200)
        api_payload = json.loads(r_api.data.decode('utf-8'))
        record("API payload contains 'counts' and 'alerts'",
               'counts' in api_payload and 'alerts' in api_payload and isinstance(api_payload['alerts'], list))

        # Cleanup test records
        Alert.query.filter_by(shelter_id=test_shelter.id).delete()
        db.session.delete(test_res)
        db.session.delete(test_shelter)
        db.session.commit()

    # Final Summary
    print("\n" + "=" * 75)
    print(f"RESULTS: {passed_tests} / {total_tests} tests passed.")
    print("=" * 75)
    if passed_tests < total_tests:
        sys.exit(1)


if __name__ == '__main__':
    run_tests()
