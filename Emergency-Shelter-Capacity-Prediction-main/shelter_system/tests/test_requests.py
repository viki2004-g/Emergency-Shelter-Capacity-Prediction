"""
tests/test_requests.py — Tests for Shelter Request Management.

Tests:
  1. ShelterRequest model:
     - All fields: group_size, lat, lng, location_name, requesting_team, contact_phone
     - Breakdown counts: injured_count, elderly_count, children_count
     - Special requirements: accessibility_requirements, medical_requirements, other_special_requirements
     - Properties: has_special_needs, special_needs_list, status_label, to_dict()
  2. Validation rules:
     - group_size must be > 0
     - people counts cannot be negative (injured, elderly, children >= 0)
     - latitude/longitude bounds
  3. HTTP endpoints:
     - GET /requests/
     - GET /requests/new
     - POST /requests/new (successful creation and validation errors)
     - GET /requests/<id>
     - POST /requests/<id>/status
"""

import sys
import os
import warnings

warnings.filterwarnings('ignore', category=DeprecationWarning)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from app import create_app
from extensions import db, bcrypt
from models import ShelterRequest, User
from routes.requests import _validate_request_form


def run_tests():
    app = create_app('testing')
    passed = 0
    failed = 0

    def check(name, condition, details=""):
        nonlocal passed, failed
        if condition:
            print(f"  [PASS] {name}")
            passed += 1
        else:
            print(f"  [FAIL] {name} -- {details}")
            failed += 1

    with app.app_context():
        db.create_all()

        print("\n==================================================")
        print("Suite 1: Form Validation Logic")
        print("==================================================")

        # 1. Valid form submission
        valid_form = {
            'group_size': '25',
            'latitude': '18.520430',
            'longitude': '73.856744',
            'location_name': 'Shivajinagar Bridge',
            'requesting_team': 'NDRF Team 1',
            'contact_phone': '9876543210',
            'injured_count': '3',
            'elderly_count': '4',
            'children_count': '6',
            'accessibility_requirements': '2 wheelchair users',
            'medical_requirements': 'First aid for head injury',
            'other_special_requirements': 'Infant milk needed',
            'notes': 'Arriving by bus in 30 mins',
        }
        errors, data = _validate_request_form(valid_form)
        check("Valid form produces no errors", len(errors) == 0, str(errors))
        check("Clean data has group_size = 25", data.get('group_size') == 25)
        check("Clean data has injured_count = 3", data.get('injured_count') == 3)

        # 2. group_size must be > 0
        errs, _ = _validate_request_form({**valid_form, 'group_size': '0'})
        check("group_size = 0 is rejected", 'group_size' in errs)

        errs, _ = _validate_request_form({**valid_form, 'group_size': '-5'})
        check("group_size = -5 is rejected", 'group_size' in errs)

        errs, _ = _validate_request_form({**valid_form, 'group_size': 'abc'})
        check("Non-numeric group_size is rejected", 'group_size' in errs)

        # 3. People counts cannot be negative
        errs, _ = _validate_request_form({**valid_form, 'injured_count': '-1'})
        check("injured_count = -1 is rejected", 'injured_count' in errs)

        errs, _ = _validate_request_form({**valid_form, 'elderly_count': '-2'})
        check("elderly_count = -2 is rejected", 'elderly_count' in errs)

        errs, _ = _validate_request_form({**valid_form, 'children_count': '-3'})
        check("children_count = -3 is rejected", 'children_count' in errs)

        # 4. Latitude and Longitude validation
        errs, _ = _validate_request_form({**valid_form, 'latitude': '95.0'})
        check("Latitude > 90 is rejected", 'latitude' in errs)

        errs, _ = _validate_request_form({**valid_form, 'longitude': '-190.0'})
        check("Longitude < -180 is rejected", 'longitude' in errs)

        # 5. Count exceeding total group size
        errs, _ = _validate_request_form({**valid_form, 'group_size': '10', 'injured_count': '15'})
        check("Injured count > group size is rejected", 'injured_count' in errs)

        print("\n==================================================")
        print("Suite 2: ShelterRequest Model & Properties")
        print("==================================================")

        # Clean up any leftover test user
        old_u = User.query.filter_by(email='responder_test@test.gov').first()
        if old_u:
            # delete existing requests by old_u first
            ShelterRequest.query.filter_by(submitted_by=old_u.id).delete()
            db.session.delete(old_u)
            db.session.commit()

        # Create responder with valid bcrypt hash
        user = User(
            full_name='Test Responder',
            email='responder_test@test.gov',
            password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8'),
            role='responder'
        )
        db.session.add(user)
        db.session.commit()

        req = ShelterRequest(
            submitted_by=user.id,
            group_size=30,
            latitude=18.5144,
            longitude=73.8415,
            location_name='Deccan Gymkhana',
            requesting_team='Quick Response Squad 4',
            contact_phone='9123456780',
            injured_count=2,
            elderly_count=5,
            children_count=8,
            accessibility_requirements='Wheelchair access required',
            medical_requirements='Diabetic patient needs cold storage',
            other_special_requirements='Vegetarian meals',
            notes='Urgent dispatch requested',
            status='pending',
            submitted_at=datetime.utcnow()
        )
        req.sync_boolean_flags()
        db.session.add(req)
        db.session.commit()

        check("Request inserted in DB with ID", req.id is not None)
        check("req.group_size == 30", req.group_size == 30)
        check("req.requesting_team correct", req.requesting_team == 'Quick Response Squad 4')
        check("req.has_special_needs is True", req.has_special_needs is True)
        check("req.has_injured is True", req.has_injured is True)
        check("req.has_elderly is True", req.has_elderly is True)
        check("req.has_children is True", req.has_children is True)
        check("req.has_disabled is True", req.has_disabled is True)
        check("special_needs_list contains 'Injured: 2'", "Injured: 2" in req.special_needs_list)
        check("special_needs_list contains 'Elderly: 5'", "Elderly: 5" in req.special_needs_list)
        check("special_needs_list contains 'Children: 8'", "Children: 8" in req.special_needs_list)
        check("status_label == 'Pending Allocation'", req.status_label == 'Pending Allocation')

        d = req.to_dict()
        check("to_dict() contains group_size", d.get('group_size') == 30)
        check("to_dict() contains requesting_team", d.get('requesting_team') == 'Quick Response Squad 4')

        print("\n==================================================")
        print("Suite 3: HTTP Endpoints Integration")
        print("==================================================")

        client = app.test_client()

        # Unauthenticated request redirects
        resp = client.get('/requests/')
        check("Unauthenticated GET /requests/ redirects to login (302)", resp.status_code == 302)

        # Authenticate by logging in via POST /auth/login
        login_res = client.post(
            '/auth/login',
            data={'email': 'responder_test@test.gov', 'password': 'Password@123'},
            follow_redirects=True
        )
        check("Responder logged in via /auth/login", login_res.status_code == 200)

        # GET /requests/
        resp_list = client.get('/requests/')
        check("GET /requests/ returns 200 OK", resp_list.status_code == 200)
        check("List page contains 'Group Shelter Requests'", b"Group Shelter Requests" in resp_list.data)
        check("List page shows created request location", b"Deccan Gymkhana" in resp_list.data)

        # GET /requests/new
        resp_new = client.get('/requests/new')
        check("GET /requests/new returns 200 OK", resp_new.status_code == 200)
        check("Form page contains 'New Shelter Request'", b"New Shelter Request" in resp_new.data)
        check("Form contains Section 1, 2, 3",
              b"Requesting Unit" in resp_new.data and b"Group Size" in resp_new.data and b"Special Assistance" in resp_new.data)

        # POST /requests/new with valid data
        post_data = {
            'group_size': '15',
            'latitude': '18.5204',
            'longitude': '73.8567',
            'location_name': 'Kothrud Rescue Center',
            'requesting_team': 'Civil Defense Unit',
            'contact_phone': '9988776655',
            'injured_count': '1',
            'elderly_count': '2',
            'children_count': '3',
            'accessibility_requirements': '1 ramp required',
            'medical_requirements': 'First aid bandage',
            'other_special_requirements': '',
            'notes': 'Family ready to move',
        }
        resp_post = client.post('/requests/new', data=post_data, follow_redirects=True)
        check("POST /requests/new succeeds (200 follow redirect)", resp_post.status_code == 200)
        check("Detail page displays created group size 15", b"Group of 15" in resp_post.data)
        check("Detail page displays landmark 'Kothrud Rescue Center'", b"Kothrud Rescue Center" in resp_post.data)

        # POST /requests/new with validation errors (group_size = 0)
        bad_post = client.post(
            '/requests/new',
            data={**post_data, 'group_size': '0'},
            follow_redirects=True
        )
        check("POST group_size = 0 rejected with error flash", b"greater than zero" in bad_post.data)

        # POST /requests/new with negative counts
        bad_counts = client.post(
            '/requests/new',
            data={**post_data, 'injured_count': '-5'},
            follow_redirects=True
        )
        check("POST negative count rejected with error message", b"cannot be negative" in bad_counts.data)

        # GET /requests/<id>
        resp_detail = client.get(f'/requests/{req.id}')
        check("GET /requests/<id> returns 200 OK", resp_detail.status_code == 200)
        check("Detail page displays group size 30", b"Group of 30" in resp_detail.data)
        check("Detail page displays Injured count 2", b"Injured" in resp_detail.data)
        check("Detail page displays Elderly count 5", b"Elderly" in resp_detail.data)
        check("Detail page displays Children count 8", b"Children" in resp_detail.data)

        # POST /requests/<id>/status to cancel
        resp_cancel = client.post(
            f'/requests/{req.id}/status',
            data={'status': 'cancelled'},
            follow_redirects=True
        )
        check("POST status update to cancelled succeeds", resp_cancel.status_code == 200)
        db.session.refresh(req)
        check("Request status updated to 'cancelled'", req.status == 'cancelled')

        # Clean up all requests created by user before deleting user
        ShelterRequest.query.filter_by(submitted_by=user.id).delete()
        db.session.delete(user)
        db.session.commit()

        print("\n==================================================")
        print(f"Total Tests Run: {passed + failed}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print("==================================================")

        return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
