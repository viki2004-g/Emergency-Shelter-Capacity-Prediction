"""
tests/test_system_verification.py — Complete System Verification Test Suite.

Covers all 8 specified verification domains:
  1. Authentication
     - valid login
     - invalid login
     - authorization
  2. Shelters
     - create
     - update
     - invalid capacity
     - unauthorized access
  3. Occupancy
     - available capacity calculation
     - safe capacity
     - critical status
     - overcrowding
  4. Requests
     - valid request
     - invalid group size
     - invalid people counts
  5. Recommendation
     - suitable shelter
     - unsuitable shelter
     - insufficient capacity
     - special requirements
  6. Prediction
     - historical data
     - future occupancy
     - invalid/no history
  7. Redistribution
     - single shelter possible
     - multiple shelters required
     - impossible allocation
     - total allocation validation
  8. Transactions
     - successful allocation
     - rollback
     - concurrent capacity protection
"""

import os
import sys
import threading
import time
import warnings
from datetime import datetime, timedelta
from unittest.mock import patch

# Suppress deprecation warnings for cleaner test output
warnings.filterwarnings('ignore', category=DeprecationWarning)

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db, bcrypt
from models.user import User
from models.shelter import Shelter
from models.facility import ShelterFacility
from models.resource import Resource
from models.request import ShelterRequest
from models.allocation import Allocation
from models.occupancy import OccupancyHistory
from routes.requests import _validate_request_form
from routes.shelters import _validate_shelter_form
from services.capacity import (
    calculate_available_capacity,
    calculate_occupancy_percentage,
    calculate_safe_capacity,
    calculate_safe_available_capacity,
    determine_occupancy_status,
)
from services.recommendation import evaluate_shelter_candidates
from services.prediction import (
    predict_shelter_occupancy,
    _calculate_rate,
)
from services.redistribution import plan_group_redistribution
from services.allocation import (
    confirm_allocation,
    InsufficientCapacityError,
    GroupSizeMismatchError,
    InvalidAllocationError,
)


def run_all_tests():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False

    passed = 0
    failed = 0
    suite_results = {}

    def check(suite_name: str, name: str, condition: bool, details: str = ""):
        nonlocal passed, failed
        if suite_name not in suite_results:
            suite_results[suite_name] = {'passed': 0, 'failed': 0}
        if condition:
            print(f"  [PASS] {name}")
            passed += 1
            suite_results[suite_name]['passed'] += 1
        else:
            print(f"  [FAIL] {name} -- {details}")
            failed += 1
            suite_results[suite_name]['failed'] += 1

    # Pre-setup users in database
    with app.app_context():
        admin_user = User.query.filter_by(email='admin@shelter.gov').first()
        if not admin_user:
            admin_user = User(
                full_name='System Admin',
                email='admin@shelter.gov',
                password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8'),
                role='admin',
                is_active=True
            )
            db.session.add(admin_user)

        manager_user = User.query.filter_by(email='manager1@shelter.gov').first()
        if not manager_user:
            manager_user = User(
                full_name='Shelter Manager 1',
                email='manager1@shelter.gov',
                password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8'),
                role='shelter_manager',
                is_active=True
            )
            db.session.add(manager_user)

        other_mgr = User.query.filter_by(email='manager2@shelter.gov').first()
        if not other_mgr:
            other_mgr = User(
                full_name='Shelter Manager 2',
                email='manager2@shelter.gov',
                password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8'),
                role='shelter_manager',
                is_active=True
            )
            db.session.add(other_mgr)

        citizen_user = User.query.filter_by(email='citizen@example.com').first()
        if not citizen_user:
            citizen_user = User(
                full_name='Citizen User',
                email='citizen@example.com',
                password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8'),
                role='citizen',
                is_active=True
            )
            db.session.add(citizen_user)

        inactive_user = User.query.filter_by(email='inactive@example.com').first()
        if not inactive_user:
            inactive_user = User(
                full_name='Inactive Account',
                email='inactive@example.com',
                password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8'),
                role='citizen',
                is_active=False
            )
            db.session.add(inactive_user)

        db.session.commit()
        admin_id = admin_user.id
        manager_id = manager_user.id
        other_mgr_id = other_mgr.id
        citizen_id = citizen_user.id

    # =========================================================================
    # 1. AUTHENTICATION
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 1: Authentication (Login, Invalid Credentials, Authorization)")
    print("=" * 65)

    # 1.1 Valid login
    c_valid = app.test_client()
    res_valid = c_valid.post('/auth/login', data={
        'email': 'admin@shelter.gov',
        'password': 'Password@123'
    }, follow_redirects=False)
    check("Authentication", "Valid login redirects with 302", res_valid.status_code == 302)
    check("Authentication", "Valid login sets session cookie", 'session' in res_valid.headers.get('Set-Cookie', ''))

    # 1.2 Invalid login: wrong password
    c_bad_pw = app.test_client()
    res_bad_pw = c_bad_pw.post('/auth/login', data={
        'email': 'admin@shelter.gov',
        'password': 'WrongPassword999'
    }, follow_redirects=True)
    check("Authentication", "Wrong password returns 200 with error message",
          res_bad_pw.status_code == 200 and b'Invalid email or password' in res_bad_pw.data)

    # 1.2 Invalid login: non-existent user
    c_no_user = app.test_client()
    res_no_user = c_no_user.post('/auth/login', data={
        'email': 'nonexistent_user_999@shelter.gov',
        'password': 'Password@123'
    }, follow_redirects=True)
    check("Authentication", "Non-existent user returns 200 with error message",
          res_no_user.status_code == 200 and b'Invalid email or password' in res_no_user.data)

    # 1.2 Invalid login: inactive account
    c_inactive = app.test_client()
    res_inactive = c_inactive.post('/auth/login', data={
        'email': 'inactive@example.com',
        'password': 'Password@123'
    }, follow_redirects=True)
    check("Authentication", "Inactive account login rejected",
          res_inactive.status_code == 200 and b'deactivated' in res_inactive.data)

    # 1.3 Authorization: unauthenticated access to protected route
    c_anon = app.test_client()
    res_anon = c_anon.get('/shelters/', follow_redirects=False)
    check("Authentication", "Unauthenticated request to protected route redirects (302)", res_anon.status_code == 302)
    check("Authentication", "Redirect target is login page", '/auth/login' in res_anon.headers.get('Location', ''))

    # 1.3 Authorization: citizen cannot access manager route
    c_citizen = app.test_client()
    c_citizen.post('/auth/login', data={'email': 'citizen@example.com', 'password': 'Password@123'})
    res_cit_create = c_citizen.get('/shelters/new', follow_redirects=False)
    check("Authentication", "Citizen access to /shelters/new returns 403 Forbidden", res_cit_create.status_code == 403)

    # =========================================================================
    # 2. SHELTERS
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 2: Shelters (Create, Update, Invalid Capacity, Unauthorized Access)")
    print("=" * 65)

    # 2.1 Create Shelter
    mgr_client = app.test_client()
    mgr_client.post('/auth/login', data={'email': 'manager1@shelter.gov', 'password': 'Password@123'})

    test_shelter_name = f"Test_Shelter_Verification_{int(time.time())}"
    post_create = mgr_client.post('/shelters/new', data={
        'name': test_shelter_name,
        'address': '101 Emergency Blvd, Sector 4',
        'latitude': '18.520400',
        'longitude': '73.856700',
        'max_capacity': '250',
        'current_occupancy': '50',
        'safe_limit_pct': '85',
        'status': 'active',
        'managed_by': str(manager_id),
        'has_medical_support': 'on',
        'has_wheelchair_access': 'on',
        'has_food': 'on'
    }, follow_redirects=False)
    check("Shelters", "Manager creates shelter successfully (302 redirect)", post_create.status_code == 302)

    created_shelter_id = None
    with app.app_context():
        created_shelter = Shelter.query.filter_by(name=test_shelter_name).first()
        check("Shelters", "Shelter persisted in database", created_shelter is not None)
        if created_shelter:
            created_shelter_id = created_shelter.id
            check("Shelters", "Shelter facility record auto-created", created_shelter.facility is not None)
            check("Shelters", "Shelter facility has_medical_support == True", created_shelter.facility.has_medical_support is True)
            check("Shelters", "Shelter resource record auto-created", created_shelter.resource is not None)
            check("Shelters", "Initial OccupancyHistory entry auto-created",
                  OccupancyHistory.query.filter_by(shelter_id=created_shelter.id).count() >= 1)

    # 2.2 Update Shelter
    if created_shelter_id:
        post_edit = mgr_client.post(f'/shelters/{created_shelter_id}/edit', data={
            'name': test_shelter_name + "_Updated",
            'address': '101 Emergency Blvd, Sector 4 (Renovated)',
            'latitude': '18.520400',
            'longitude': '73.856700',
            'max_capacity': '300',
            'current_occupancy': '60',
            'safe_limit_pct': '85',
            'status': 'active',
            'managed_by': str(manager_id),
        }, follow_redirects=False)
        check("Shelters", "Manager updates shelter successfully (302 redirect)", post_edit.status_code == 302)

        with app.app_context():
            sh_refreshed = db.session.get(Shelter, created_shelter_id)
            check("Shelters", "Updated name persisted in database",
                  sh_refreshed.name == test_shelter_name + "_Updated")
            check("Shelters", "Updated max_capacity persisted in database",
                  sh_refreshed.max_capacity == 300)

        # 2.4 Unauthorized Access: other manager cannot edit another manager's shelter
        other_mgr_client = app.test_client()
        other_mgr_client.post('/auth/login', data={'email': 'manager2@shelter.gov', 'password': 'Password@123'})
        res_cross_mgr = other_mgr_client.post(f'/shelters/{created_shelter_id}/edit', data={
            'name': 'Hacked Name',
            'address': 'Hacked Address',
            'latitude': '18.52',
            'longitude': '73.85',
            'max_capacity': '100',
            'current_occupancy': '10',
            'status': 'active'
        }, follow_redirects=False)
        check("Shelters", "Unauthorized manager cannot edit another manager's shelter (403)",
              res_cross_mgr.status_code == 403)

    # 2.3 Invalid Capacity Validation
    with app.app_context():
        errs_zero_cap, _ = _validate_shelter_form({'name': 'T1', 'address': 'A1', 'latitude': 0, 'longitude': 0, 'max_capacity': '0'})
        check("Shelters", "Zero max capacity rejected", 'max_capacity' in errs_zero_cap)

        errs_neg_cap, _ = _validate_shelter_form({'name': 'T1', 'address': 'A1', 'latitude': 0, 'longitude': 0, 'max_capacity': '-50'})
        check("Shelters", "Negative max capacity rejected", 'max_capacity' in errs_neg_cap)

        errs_neg_occ, _ = _validate_shelter_form({'name': 'T1', 'address': 'A1', 'latitude': 0, 'longitude': 0, 'max_capacity': '100', 'current_occupancy': '-10'})
        check("Shelters", "Negative current occupancy rejected", 'current_occupancy' in errs_neg_occ)

        errs_bad_pct, _ = _validate_shelter_form({'name': 'T1', 'address': 'A1', 'latitude': 0, 'longitude': 0, 'max_capacity': '100', 'safe_limit_pct': '150'})
        check("Shelters", "Safe limit > 100 rejected", 'safe_limit_pct' in errs_bad_pct)

    # =========================================================================
    # 3. OCCUPANCY
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 3: Occupancy (Available, Safe Capacity, Critical, Overcrowding)")
    print("=" * 65)

    # 3.1 Available capacity calculation
    check("Occupancy", "Available capacity: 500 - 300 = 200", calculate_available_capacity(500, 300) == 200)
    check("Occupancy", "Available capacity at limit: 500 - 500 = 0", calculate_available_capacity(500, 500) == 0)
    check("Occupancy", "Available capacity overcrowded: 500 - 550 = -50", calculate_available_capacity(500, 550) == -50)

    # 3.2 Safe capacity
    safe_cap_85 = calculate_safe_capacity(500, safe_limit_pct=85)
    check("Occupancy", "Safe capacity 500 @ 85% = 425", safe_cap_85 == 425)

    safe_avail_pos = calculate_safe_available_capacity(500, current_occupancy=400, safe_limit_pct=85)
    check("Occupancy", "Safe available: 425 - 400 = 25", safe_avail_pos == 25)

    safe_avail_neg = calculate_safe_available_capacity(500, current_occupancy=450, safe_limit_pct=85)
    check("Occupancy", "Safe available breached: 425 - 450 = -25", safe_avail_neg == -25)

    # 3.3 Critical status
    pct_normal = calculate_occupancy_percentage(250, 500)
    check("Occupancy", "Occupancy percentage: 250 / 500 = 50.0%", pct_normal == 50.0)
    check("Occupancy", "50.0% is classified as 'safe'", determine_occupancy_status(50.0) == 'safe')
    check("Occupancy", "70.0% is classified as 'moderate'", determine_occupancy_status(70.0) == 'moderate')
    check("Occupancy", "90.0% is classified as 'high'", determine_occupancy_status(90.0) == 'high')

    pct_crit = calculate_occupancy_percentage(485, 500)
    check("Occupancy", "485 / 500 = 97.0% is classified as 'critical'",
          pct_crit == 97.0 and determine_occupancy_status(97.0) == 'critical')

    # 3.4 Overcrowding
    pct_over = calculate_occupancy_percentage(530, 500)
    check("Occupancy", "530 / 500 = 106.0% is classified as 'overcrowded'",
          pct_over == 106.0 and determine_occupancy_status(106.0) == 'overcrowded')

    # =========================================================================
    # 4. REQUESTS
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 4: Requests (Valid Request, Invalid Group Size, Invalid Counts)")
    print("=" * 65)

    # 4.1 Valid Request
    valid_form_data = {
        'group_size': '45',
        'location_name': 'Shivajinagar Bus Stand',
        'latitude': '18.531200',
        'longitude': '73.844500',
        'requesting_team': 'NDRF Team Bravo',
        'contact_phone': '9876543210',
        'injured_count': '4',
        'elderly_count': '8',
        'children_count': '12',
    }
    val_errs, val_clean = _validate_request_form(valid_form_data)
    check("Requests", "Valid request form produces zero validation errors", len(val_errs) == 0)
    check("Requests", "Clean group_size is integer 45", val_clean.get('group_size') == 45)
    check("Requests", "Clean injured_count is 4", val_clean.get('injured_count') == 4)

    req_obj_id = None
    with app.app_context():
        req_obj = ShelterRequest(
            group_size=45,
            location_name='Shivajinagar Bus Stand',
            latitude=18.531200,
            longitude=73.844500,
            requesting_team='NDRF Team Bravo',
            contact_phone='9876543210',
            injured_count=4,
            elderly_count=8,
            children_count=12,
            accessibility_requirements='Wheelchair access required',
            status='pending',
            submitted_by=admin_id
        )
        req_obj.sync_boolean_flags()
        db.session.add(req_obj)
        db.session.commit()
        req_obj_id = req_obj.id

        check("Requests", "ShelterRequest model persisted with ID", req_obj.id is not None)
        check("Requests", "has_special_needs property is True", req_obj.has_special_needs is True)
        check("Requests", "has_injured property is True", req_obj.has_injured is True)
        check("Requests", "has_disabled property is True", req_obj.has_disabled is True)

    # 4.2 Invalid Group Size
    errs_zero_grp, _ = _validate_request_form({'group_size': '0', 'latitude': '18.5', 'longitude': '73.8'})
    check("Requests", "Group size 0 rejected", 'group_size' in errs_zero_grp)

    errs_neg_grp, _ = _validate_request_form({'group_size': '-20', 'latitude': '18.5', 'longitude': '73.8'})
    check("Requests", "Negative group size rejected", 'group_size' in errs_neg_grp)

    errs_str_grp, _ = _validate_request_form({'group_size': 'twenty', 'latitude': '18.5', 'longitude': '73.8'})
    check("Requests", "Non-numeric group size rejected", 'group_size' in errs_str_grp)

    # 4.3 Invalid People Counts
    errs_neg_inj, _ = _validate_request_form({'group_size': '20', 'injured_count': '-1', 'latitude': '18.5', 'longitude': '73.8'})
    check("Requests", "Negative injured count rejected", 'injured_count' in errs_neg_inj)

    errs_neg_eld, _ = _validate_request_form({'group_size': '20', 'elderly_count': '-3', 'latitude': '18.5', 'longitude': '73.8'})
    check("Requests", "Negative elderly count rejected", 'elderly_count' in errs_neg_eld)

    errs_neg_chi, _ = _validate_request_form({'group_size': '20', 'children_count': '-5', 'latitude': '18.5', 'longitude': '73.8'})
    check("Requests", "Negative children count rejected", 'children_count' in errs_neg_chi)

    errs_excess, _ = _validate_request_form({'group_size': '10', 'injured_count': '15', 'latitude': '18.5', 'longitude': '73.8'})
    check("Requests", "Injured count exceeding group size rejected", 'injured_count' in errs_excess)

    # =========================================================================
    # 5. RECOMMENDATION
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 5: Recommendation (Suitable, Unsuitable, Insufficient, Special Req)")
    print("=" * 65)

    rec_shelter_ids = []
    with app.app_context():
        # Create 4 controlled test shelters for recommendation
        ts_suitable = Shelter(
            name="RecTest_Suitable_Shelter",
            address="12 Central Road",
            latitude=18.520400,
            longitude=73.856700,
            max_capacity=200,
            current_occupancy=40,
            safe_limit_pct=85,  # safe cap = 170, safe available = 130
            status="active"
        )
        ts_unsuitable = Shelter(
            name="RecTest_Inactive_Shelter",
            address="34 Closed Ave",
            latitude=18.521000,
            longitude=73.857000,
            max_capacity=200,
            current_occupancy=10,
            safe_limit_pct=85,
            status="inactive"  # not operational
        )
        ts_small = Shelter(
            name="RecTest_Small_Shelter",
            address="56 Narrow Lane",
            latitude=18.522000,
            longitude=73.858000,
            max_capacity=50,
            current_occupancy=40,
            safe_limit_pct=85,  # safe cap = 42, safe available = 2
            status="active"
        )
        ts_nowheel = Shelter(
            name="RecTest_NoWheelchair_Shelter",
            address="78 Step Hill",
            latitude=18.520500,
            longitude=73.856800,
            max_capacity=200,
            current_occupancy=20,
            safe_limit_pct=85,
            status="active"
        )
        db.session.add_all([ts_suitable, ts_unsuitable, ts_small, ts_nowheel])
        db.session.commit()

        rec_shelter_ids = [ts_suitable.id, ts_unsuitable.id, ts_small.id, ts_nowheel.id]

        db.session.add(ShelterFacility(shelter_id=ts_suitable.id, has_wheelchair_access=True, has_medical_support=True))
        db.session.add(ShelterFacility(shelter_id=ts_unsuitable.id, has_wheelchair_access=True, has_medical_support=True))
        db.session.add(ShelterFacility(shelter_id=ts_small.id, has_wheelchair_access=True, has_medical_support=True))
        db.session.add(ShelterFacility(shelter_id=ts_nowheel.id, has_wheelchair_access=False, has_medical_support=True))
        db.session.commit()

        rec_req = ShelterRequest(
            group_size=30,
            latitude=18.520400,
            longitude=73.856700,
            has_disabled=True,
            accessibility_requirements="Wheelchair access needed",
            status="pending"
        )

        test_shelters = [ts_suitable, ts_unsuitable, ts_small, ts_nowheel]
        rec_result = evaluate_shelter_candidates(rec_req, shelters=test_shelters)

        # 5.1 Suitable shelter
        check("Recommendation", "Recommended shelter identified", rec_result['recommended_shelter'] is not None)
        check("Recommendation", "Suitable shelter is ranked #1",
              rec_result['recommended_shelter']['shelter'].id == ts_suitable.id)
        check("Recommendation", "Positive explainable reasons generated",
              len(rec_result['recommended_shelter']['positive_reasons']) > 0)

        # 5.2 Unsuitable shelter
        rejected_ids = [r['shelter'].id for r in rec_result['rejected_shelters']]
        check("Recommendation", "Inactive shelter is in rejected list", ts_unsuitable.id in rejected_ids)
        rej_inactive = next(r for r in rec_result['rejected_shelters'] if r['shelter'].id == ts_unsuitable.id)
        check("Recommendation", "Inactive shelter rejection reason mentions non-operational status",
              any('active' in r.lower() or 'inactive' in r.lower() or 'not operational' in r.lower() for r in rej_inactive['rejection_reasons']))

        # 5.3 Insufficient capacity
        check("Recommendation", "Small shelter (capacity 2 < 30) is in rejected list", ts_small.id in rejected_ids)
        rej_small = next(r for r in rec_result['rejected_shelters'] if r['shelter'].id == ts_small.id)
        check("Recommendation", "Small shelter rejection reason mentions capacity shortfall",
              any('capacity' in r.lower() for r in rej_small['rejection_reasons']))

        # 5.4 Special requirements
        check("Recommendation", "Shelter without wheelchair access is in rejected list", ts_nowheel.id in rejected_ids)
        rej_nowheel = next(r for r in rec_result['rejected_shelters'] if r['shelter'].id == ts_nowheel.id)
        check("Recommendation", "Rejection reason explicitly cites wheelchair access",
              any('wheelchair' in r.lower() for r in rej_nowheel['rejection_reasons']))

    # =========================================================================
    # 6. PREDICTION
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 6: Prediction (Historical Data, Future Occupancy, Invalid/No History)")
    print("=" * 65)

    # 6.1 Historical rate calculation
    now = datetime.utcnow()
    controlled_history = [
        OccupancyHistory(shelter_id=9999, occupancy=140, recorded_at=now),
        OccupancyHistory(shelter_id=9999, occupancy=120, recorded_at=now - timedelta(hours=2)),
        OccupancyHistory(shelter_id=9999, occupancy=100, recorded_at=now - timedelta(hours=4)),
    ]
    rate, elapsed = _calculate_rate(controlled_history)
    check("Prediction", "Arrival rate calculated correctly: (140 - 100) / 4h = +10.0 people/hr",
          rate == 10.0 and elapsed == 4.0)

    # Declining rate
    declining_history = [
        OccupancyHistory(shelter_id=9999, occupancy=80, recorded_at=now),
        OccupancyHistory(shelter_id=9999, occupancy=100, recorded_at=now - timedelta(hours=2)),
    ]
    rate_dec, _ = _calculate_rate(declining_history)
    check("Prediction", "Declining arrival rate: (80 - 100) / 2h = -10.0 people/hr", rate_dec == -10.0)

    pred_shelter_ids = []
    with app.app_context():
        # 6.2 Future occupancy projection
        ts_pred = Shelter(
            name="PredTest_Shelter",
            address="99 Future Way",
            latitude=18.52,
            longitude=73.85,
            max_capacity=200,
            current_occupancy=140,
            safe_limit_pct=85,
            status="active"
        )
        db.session.add(ts_pred)
        db.session.commit()
        pred_shelter_ids.append(ts_pred.id)

        db.session.add(OccupancyHistory(shelter_id=ts_pred.id, occupancy=100, recorded_at=now - timedelta(hours=4)))
        db.session.add(OccupancyHistory(shelter_id=ts_pred.id, occupancy=120, recorded_at=now - timedelta(hours=2)))
        db.session.add(OccupancyHistory(shelter_id=ts_pred.id, occupancy=140, recorded_at=now))
        db.session.commit()

        pred_result = predict_shelter_occupancy(ts_pred, hours_ahead=6)
        check("Prediction", "has_prediction is True with valid history", pred_result['has_prediction'] is True)
        check("Prediction", "Projected occupancy formula (140 + 10*6 = 200, clamped at max 200)",
              pred_result['predicted_occupancy'] == 200)
        check("Prediction", "Predicted % is 100.0%", pred_result['predicted_pct'] == 100.0)
        check("Prediction", "Risk at 100% is 'critical'", pred_result['overload_risk'] == 'critical')
        check("Prediction", "Forecast disclaimer is explicitly present", len(pred_result['disclaimer']) > 0)

        # 6.3 Invalid / No history
        ts_no_hist = Shelter(
            name="PredTest_NoHistory",
            address="100 Empty St",
            latitude=18.52,
            longitude=73.85,
            max_capacity=150,
            current_occupancy=50,
            safe_limit_pct=85,
            status="active"
        )
        db.session.add(ts_no_hist)
        db.session.commit()
        pred_shelter_ids.append(ts_no_hist.id)

        pred_empty = predict_shelter_occupancy(ts_no_hist, hours_ahead=6)
        check("Prediction", "No history reports has_prediction=False", pred_empty['has_prediction'] is False)
        check("Prediction", "No history defaults rate to 0.0", pred_empty['arrival_rate_per_hour'] == 0.0)
        check("Prediction", "No history predicted occupancy equals current occupancy (50)",
              pred_empty['predicted_occupancy'] == 50)

        # Single record edge case
        rate_single, _ = _calculate_rate([OccupancyHistory(shelter_id=9999, occupancy=50, recorded_at=now)])
        check("Prediction", "Single history record returns rate 0.0", rate_single == 0.0)

    # =========================================================================
    # 7. REDISTRIBUTION
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 7: Redistribution (Single, Multiple Shelters, Impossible, Validation)")
    print("=" * 65)

    redist_shelter_ids = []
    with app.app_context():
        # 7.1 Single shelter possible
        sh_redist_1 = Shelter(
            name="Redist_Shelter_1",
            address="1 Alpha Way",
            latitude=18.5204,
            longitude=73.8567,
            max_capacity=100,
            current_occupancy=20,
            safe_limit_pct=80,  # safe cap = 80, safe available = 60
            status="active"
        )
        sh_redist_2 = Shelter(
            name="Redist_Shelter_2",
            address="2 Beta Way",
            latitude=18.5205,
            longitude=73.8568,
            max_capacity=100,
            current_occupancy=30,
            safe_limit_pct=80,  # safe cap = 80, safe available = 50
            status="active"
        )
        sh_redist_3 = Shelter(
            name="Redist_Shelter_3",
            address="3 Gamma Way",
            latitude=18.5206,
            longitude=73.8569,
            max_capacity=100,
            current_occupancy=50,
            safe_limit_pct=80,  # safe cap = 80, safe available = 30
            status="active"
        )
        db.session.add_all([sh_redist_1, sh_redist_2, sh_redist_3])
        db.session.commit()

        redist_shelter_ids = [sh_redist_1.id, sh_redist_2.id, sh_redist_3.id]
        redist_pool = [sh_redist_1, sh_redist_2, sh_redist_3]

        # Group fits entirely into sh_redist_1 (needs 40 <= safe available 60)
        req_single = ShelterRequest(group_size=40, latitude=18.5204, longitude=73.8567, status='pending')
        plan_single = plan_group_redistribution(req_single, shelters=redist_pool)
        check("Redistribution", "Single shelter fits group: is_possible == True", plan_single['is_possible'] is True)
        check("Redistribution", "Single shelter fulfills all 40 evacuees", plan_single['total_allocated'] == 40)
        check("Redistribution", "Allocations list has exactly 1 shelter entry", len(plan_single['allocations']) == 1)
        check("Redistribution", "Assigned shelter is sh_redist_1 with count 40",
              plan_single['allocations'][0]['shelter_id'] == sh_redist_1.id and plan_single['allocations'][0]['allocated_count'] == 40)

        # 7.2 Multiple shelters required
        # Group size 100 > safe available of any single shelter (60, 50, 30)
        # Total network capacity = 60 + 50 + 30 = 140 >= 100
        req_multi = ShelterRequest(group_size=100, latitude=18.5204, longitude=73.8567, status='pending')
        plan_multi = plan_group_redistribution(req_multi, shelters=redist_pool)
        check("Redistribution", "Multi-shelter plan is_possible == True", plan_multi['is_possible'] is True)
        check("Redistribution", "Multi-shelter allocates exactly 100 evacuees", plan_multi['total_allocated'] == 100)
        check("Redistribution", "Multi-shelter allocates across > 1 shelter", len(plan_multi['allocations']) > 1)

        # 7.4 Total allocation validation
        sum_allocated = sum(a['allocated_count'] for a in plan_multi['allocations'])
        check("Redistribution", "Validation: sum(allocations) == requested group size (100)",
              sum_allocated == 100)
        all_safe = all(a['allocated_count'] <= a['safe_available_before'] for a in plan_multi['allocations'])
        check("Redistribution", "Validation: No shelter exceeded safe available capacity", all_safe)

        # 7.3 Impossible allocation (deficit)
        req_huge = ShelterRequest(group_size=200, latitude=18.5204, longitude=73.8567, status='pending')
        plan_huge = plan_group_redistribution(req_huge, shelters=redist_pool)
        check("Redistribution", "Impossible allocation: is_possible == False", plan_huge['is_possible'] is False)
        check("Redistribution", "Unallocated count accurately calculated (200 - 140 = 60)",
              plan_huge['unallocated_count'] == 60)
        check("Redistribution", "Clear deficit explanation provided",
              'deficit' in plan_huge['explanation'].lower() or 'impossible' in plan_huge['explanation'].lower())

    # =========================================================================
    # 8. TRANSACTIONS
    # =========================================================================
    print("\n" + "=" * 65)
    print("Suite 8: Transactions (Success, Rollback, Concurrent Row-Locking)")
    print("=" * 65)

    tx_shelter_id = None
    tx_req_id = None
    tx_fail_id = None
    tx_conc_ids = []

    with app.app_context():
        tx_shelter = Shelter(
            name="Tx_Protected_Shelter",
            address="77 ACID Lane",
            latitude=18.52,
            longitude=73.85,
            max_capacity=100,
            current_occupancy=20,
            safe_limit_pct=80,  # safe cap = 80, safe available = 60
            status="active"
        )
        db.session.add(tx_shelter)
        db.session.commit()
        tx_shelter_id = tx_shelter.id

        tx_req = ShelterRequest(
            group_size=25,
            latitude=18.52,
            longitude=73.85,
            status="pending",
            submitted_by=admin_id
        )
        db.session.add(tx_req)
        db.session.commit()
        tx_req_id = tx_req.id

        # 8.1 Successful allocation transaction
        tx_res = confirm_allocation(
            request_id=tx_req.id,
            allocations=[{'shelter_id': tx_shelter.id, 'allocated_count': 25}],
            confirmed_by_user_id=admin_id,
            notes="Standard successful allocation"
        )
        check("Transactions", "confirm_allocation returned success == True", tx_res.get('success') is True)
        check("Transactions", "total_allocated is 25", tx_res.get('total_allocated') == 25)

        db.session.refresh(tx_shelter)
        db.session.refresh(tx_req)
        check("Transactions", "Shelter occupancy incremented (20 -> 45)", tx_shelter.current_occupancy == 45)
        check("Transactions", "Shelter safe available capacity updated (60 -> 35)", tx_shelter.safe_available_capacity == 35)
        check("Transactions", "ShelterRequest status updated to 'allocated'", tx_req.status == 'allocated')

        alloc_recs = Allocation.query.filter_by(request_id=tx_req.id).all()
        check("Transactions", "Confirmed Allocation record created in DB", len(alloc_recs) == 1 and alloc_recs[0].confirmed is True)
        check("Transactions", "OccupancyHistory audit log entry persisted",
              OccupancyHistory.query.filter_by(shelter_id=tx_shelter.id, occupancy=45).count() >= 1)

        # 8.2 Rollback Guarantee (Capacity breach & Group mismatch)
        # Attempt to allocate 50 to tx_shelter which only has 35 safe spots left
        tx_req_fail = ShelterRequest(
            group_size=50,
            latitude=18.52,
            longitude=73.85,
            status="pending",
            submitted_by=admin_id
        )
        db.session.add(tx_req_fail)
        db.session.commit()
        tx_fail_id = tx_req_fail.id

        insufficient_caught = False
        try:
            confirm_allocation(
                request_id=tx_req_fail.id,
                allocations=[{'shelter_id': tx_shelter.id, 'allocated_count': 50}],
                confirmed_by_user_id=admin_id
            )
        except InsufficientCapacityError:
            insufficient_caught = True

        check("Transactions", "Capacity breach raises InsufficientCapacityError", insufficient_caught)
        db.session.refresh(tx_shelter)
        db.session.refresh(tx_req_fail)
        check("Transactions", "Rollback: Shelter occupancy unchanged (remains 45)", tx_shelter.current_occupancy == 45)
        check("Transactions", "Rollback: Request status remains 'pending'", tx_req_fail.status == 'pending')
        check("Transactions", "Rollback: Zero orphaned Allocation records created",
              Allocation.query.filter_by(request_id=tx_req_fail.id).count() == 0)

        # Group size mismatch rollback
        mismatch_caught = False
        try:
            confirm_allocation(
                request_id=tx_req_fail.id,
                allocations=[{'shelter_id': tx_shelter.id, 'allocated_count': 30}],  # 30 != 50
                confirmed_by_user_id=admin_id
            )
        except GroupSizeMismatchError:
            mismatch_caught = True

        check("Transactions", "Group size mismatch raises GroupSizeMismatchError", mismatch_caught)

        # 8.3 Concurrency Protection (Multithreaded Race Condition & Row-Locking)
        # tx_shelter has safe capacity 80, current 45 -> 35 safe spaces remain
        # We launch 2 concurrent threads each trying to claim 25 spaces (total 50 > 35)
        # With row-locking (SELECT ... FOR UPDATE), exactly 1 thread must succeed and 1 must fail
        req_conc_1 = ShelterRequest(group_size=25, latitude=18.52, longitude=73.85, status='pending', submitted_by=admin_id)
        req_conc_2 = ShelterRequest(group_size=25, latitude=18.52, longitude=73.85, status='pending', submitted_by=admin_id)
        db.session.add_all([req_conc_1, req_conc_2])
        db.session.commit()
        tx_conc_ids = [req_conc_1.id, req_conc_2.id]

        conc_results = []

        def worker(r_id):
            with app.app_context():
                try:
                    res = confirm_allocation(
                        request_id=r_id,
                        allocations=[{'shelter_id': tx_shelter_id, 'allocated_count': 25}],
                        confirmed_by_user_id=admin_id
                    )
                    conc_results.append(('SUCCESS', res))
                except InsufficientCapacityError as ex:
                    conc_results.append(('INSUFFICIENT_CAP', str(ex)))
                except Exception as ex:
                    conc_results.append(('ERROR', str(ex)))
                finally:
                    db.session.remove()

        t1 = threading.Thread(target=worker, args=(req_conc_1.id,))
        t2 = threading.Thread(target=worker, args=(req_conc_2.id,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        success_count = sum(1 for status, _ in conc_results if status == 'SUCCESS')
        fail_count = sum(1 for status, _ in conc_results if status == 'INSUFFICIENT_CAP')

        check("Transactions", "Concurrency: Exactly one thread succeeded (claimed 25 of 35 spots)", success_count == 1)
        check("Transactions", "Concurrency: Exactly one thread failed with InsufficientCapacityError", fail_count == 1)

        db.session.remove()
        tx_shelter_fresh = db.session.get(Shelter, tx_shelter_id)
        check("Transactions", "Concurrency: Final occupancy is 70 (45 + 25), safe limit (80) never breached",
              tx_shelter_fresh.current_occupancy == 70 and tx_shelter_fresh.safe_available_capacity == 10)

    # =========================================================================
    # CLEANUP
    # =========================================================================
    print("\nCleaning up test artifacts...")
    with app.app_context():
        all_shelter_ids = [created_shelter_id] + rec_shelter_ids + pred_shelter_ids + redist_shelter_ids + [tx_shelter_id]
        for sid in all_shelter_ids:
            if sid:
                Allocation.query.filter_by(shelter_id=sid).delete()
                OccupancyHistory.query.filter_by(shelter_id=sid).delete()
                ShelterFacility.query.filter_by(shelter_id=sid).delete()
                Resource.query.filter_by(shelter_id=sid).delete()
                Shelter.query.filter_by(id=sid).delete()

        all_req_ids = [req_obj_id, tx_req_id, tx_fail_id] + tx_conc_ids
        for rid in all_req_ids:
            if rid:
                Allocation.query.filter_by(request_id=rid).delete()
                ShelterRequest.query.filter_by(id=rid).delete()

        db.session.commit()
    print("Cleanup completed.")

    # =========================================================================
    # FINAL REPORT SUMMARY
    # =========================================================================
    print("\n" + "=" * 65)
    print("COMPREHENSIVE TEST SUITE REPORT")
    print("=" * 65)
    for suite_name, counts in suite_results.items():
        status_str = "PASS" if counts['failed'] == 0 else "FAIL"
        print(f"  [{status_str}] {suite_name:<18} : {counts['passed']:>2} passed, {counts['failed']:>2} failed")
    print("-" * 65)
    print(f"  TOTAL TESTS RUN     : {passed + failed}")
    print(f"  PASSED              : {passed}")
    print(f"  FAILED              : {failed}")
    print("=" * 65)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
