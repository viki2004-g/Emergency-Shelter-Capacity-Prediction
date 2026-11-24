"""
tests/test_recommendation.py — Comprehensive test suite for the Shelter Recommendation Engine.

Tests:
  Suite 1: Configurable Weights & Normalization
  Suite 2: Component Scoring Functions (Distance, Capacity, Facilities, Resources)
  Suite 3: Strict Hard Constraint Filtering (Wheelchair, Medical, Capacity, Operational Status)
  Suite 4: Explainability & Positive/Negative Reason Generation
  Suite 5: Multiple End-to-End Scenario Evaluations
  Suite 6: HTTP Route Integration & Access Control
"""

import sys
import os
import unittest
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db
from models.user import User
from models.shelter import Shelter
from models.facility import ShelterFacility
from models.resource import Resource
from models.request import ShelterRequest
from models.occupancy import OccupancyHistory
from services.scoring import (
    get_configured_weights,
    calculate_distance_score,
    calculate_capacity_score,
    calculate_facilities_score,
    calculate_resources_score,
    calculate_weighted_score,
    DEFAULT_WEIGHTS,
)
from services.recommendation import evaluate_shelter_candidates, DISCLAIMER_TEXT
from services.distance import haversine_distance


total_tests = 0
passed_tests = 0


def record_test(label: str, passed: bool, detail: str = ""):
    global total_tests, passed_tests
    total_tests += 1
    if passed:
        passed_tests += 1
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label} -- {detail}")


def run_all_tests():
    global total_tests, passed_tests
    app = create_app()

    with app.app_context():
        print("\n" + "=" * 60)
        print("Suite 1: Configurable Weights & Normalization")
        print("=" * 60)

        # 1.1 Default weights fallback
        w_def = get_configured_weights()
        record_test(
            "Default weights loaded and sum to 1.0",
            abs(sum(w_def.values()) - 1.0) < 0.001,
            f"Sum: {sum(w_def.values())}"
        )

        # 1.2 Custom weights normalization
        custom = {'distance': 0.5, 'capacity': 0.5, 'facilities': 0.0, 'resources': 0.0}
        w_norm = get_configured_weights(custom)
        record_test(
            "Custom weights normalized accurately",
            abs(w_norm['distance'] - 0.5) < 0.001 and abs(w_norm['capacity'] - 0.5) < 0.001
        )

        # 1.3 Unnormalized inputs (e.g. 50, 50, 0, 0)
        unnorm = {'distance': 50, 'capacity': 50, 'facilities': 0, 'resources': 0}
        w_rescaled = get_configured_weights(unnorm)
        record_test(
            "Unscaled weights (sum 100) normalized to 1.0",
            abs(w_rescaled['distance'] - 0.5) < 0.001 and abs(sum(w_rescaled.values()) - 1.0) < 0.001
        )

        # 1.4 Negative values cleaned to 0
        neg_w = {'distance': -10, 'capacity': 1.0, 'facilities': 0, 'resources': 0}
        w_clean = get_configured_weights(neg_w)
        record_test(
            "Negative weights coerced to non-negative and normalized",
            w_clean['distance'] == 0.0 and w_clean['capacity'] == 1.0
        )

        print("\n" + "=" * 60)
        print("Suite 2: Component Scoring Functions")
        print("=" * 60)

        # 2.1 Distance Scoring
        d0 = calculate_distance_score(0.0)
        record_test("Distance 0 km scores 100.0", d0 == 100.0, f"Got {d0}")

        d25 = calculate_distance_score(25.0, max_km=50.0)
        record_test("Distance 25 km (50% max) scores 50.0", d25 == 50.0, f"Got {d25}")

        d50 = calculate_distance_score(50.0, max_km=50.0)
        record_test("Distance 50+ km scores 0.0", d50 == 0.0, f"Got {d50}")

        # 2.2 Weighted Score Aggregation
        weighted_out = calculate_weighted_score(
            dist_score=100.0,
            cap_score=100.0,
            fac_score=100.0,
            res_score=100.0
        )
        record_test("All 100s produce total_score 100.0", weighted_out['total_score'] == 100.0)
        record_test("Components dictionary contains all 4 keys", set(weighted_out['components'].keys()) == {'distance', 'capacity', 'facilities', 'resources'})

        # Setup test objects for Suites 3-5
        admin_user = User.query.filter_by(role='admin').first()
        if not admin_user:
            admin_user = User(email='test_admin@shelter.gov', full_name='Test Admin', role='admin')
            admin_user.set_password('Password@123')
            db.session.add(admin_user)
            db.session.commit()

        # Clean existing test shelters
        Shelter.query.filter(Shelter.name.like('TestRec_%')).delete(synchronize_session=False)
        ShelterRequest.query.filter(ShelterRequest.location_name.like('TestRec_%')).delete(synchronize_session=False)
        db.session.commit()

        # Create test shelters with distinct capabilities:
        # Shelter A: Active, Max 500, Occ 100 (Safe avail: 325), Has Wheelchair & Medical, close (18.5204, 73.8567)
        sh_a = Shelter(
            name='TestRec_Shelter_A_AllCapabilities',
            address='10 Central Way',
            latitude=18.5204,
            longitude=73.8567,
            max_capacity=500,
            current_occupancy=100,
            status='active',
            safe_limit_pct=85
        )
        db.session.add(sh_a)
        db.session.flush()

        fac_a = ShelterFacility(
            shelter_id=sh_a.id,
            has_wheelchair_access=True,
            has_medical_support=True,
            has_food=True,
            has_running_water=True,
            has_electricity=True,
            has_toilets=True,
            has_kitchen=True,
            has_family_area=True
        )
        res_a = Resource(
            shelter_id=sh_a.id,
            beds_available=300,
            food_portions=1000,
            water_litres=2500,
            medicine_kits=30,
            blankets=300
        )
        db.session.add_all([fac_a, res_a])

        # Shelter B: Active, Max 200, Occ 50 (Safe avail: 120), Has Medical, NO Wheelchair, closer
        sh_b = Shelter(
            name='TestRec_Shelter_B_NoWheelchair',
            address='20 Hill Road',
            latitude=18.5210,
            longitude=73.8570,
            max_capacity=200,
            current_occupancy=50,
            status='active',
            safe_limit_pct=85
        )
        db.session.add(sh_b)
        db.session.flush()

        fac_b = ShelterFacility(
            shelter_id=sh_b.id,
            has_wheelchair_access=False,
            has_medical_support=True,
            has_food=True,
            has_running_water=True,
            has_electricity=True,
            has_toilets=True
        )
        res_b = Resource(
            shelter_id=sh_b.id,
            beds_available=100,
            food_portions=400,
            water_litres=800,
            medicine_kits=10,
            blankets=100
        )
        db.session.add_all([fac_b, res_b])

        # Shelter C: Active, Max 200, Occ 50, Has Wheelchair, NO Medical
        sh_c = Shelter(
            name='TestRec_Shelter_C_NoMedical',
            address='30 Park Avenue',
            latitude=18.5300,
            longitude=73.8600,
            max_capacity=200,
            current_occupancy=50,
            status='active',
            safe_limit_pct=85
        )
        db.session.add(sh_c)
        db.session.flush()

        fac_c = ShelterFacility(
            shelter_id=sh_c.id,
            has_wheelchair_access=True,
            has_medical_support=False,
            has_food=True,
            has_running_water=True,
            has_electricity=True,
            has_toilets=True
        )
        res_c = Resource(
            shelter_id=sh_c.id,
            beds_available=100,
            food_portions=400,
            water_litres=800,
            medicine_kits=0,
            blankets=100
        )
        db.session.add_all([fac_c, res_c])

        # Shelter D: INACTIVE (Closed/damaged)
        sh_d = Shelter(
            name='TestRec_Shelter_D_Inactive',
            address='40 River Side',
            latitude=18.5205,
            longitude=73.8568,
            max_capacity=500,
            current_occupancy=0,
            status='inactive',
            safe_limit_pct=85
        )
        db.session.add(sh_d)
        db.session.flush()
        db.session.add(ShelterFacility(shelter_id=sh_d.id, has_wheelchair_access=True, has_medical_support=True))
        db.session.add(Resource(shelter_id=sh_d.id, beds_available=500))

        # Shelter E: Nearly Full (Safe capacity = 85, Occ = 80 -> safe available = 5)
        sh_e = Shelter(
            name='TestRec_Shelter_E_SmallHeadroom',
            address='50 Narrow Lane',
            latitude=18.5204,
            longitude=73.8567,
            max_capacity=100,
            current_occupancy=80,
            status='active',
            safe_limit_pct=85
        )
        db.session.add(sh_e)
        db.session.flush()
        db.session.add(ShelterFacility(shelter_id=sh_e.id, has_wheelchair_access=True, has_medical_support=True))
        db.session.add(Resource(shelter_id=sh_e.id, beds_available=20))

        db.session.commit()

        test_shelters = [sh_a, sh_b, sh_c, sh_d, sh_e]

        print("\n" + "=" * 60)
        print("Suite 3: Strict Hard Constraint Filtering")
        print("=" * 60)

        # 3.1 Wheelchair Requirement Hard Exclusion
        # Request requiring wheelchair access: Shelter B lacks it -> MUST be excluded
        req_wheelchair = ShelterRequest(
            submitted_by=admin_user.id,
            group_size=10,
            latitude=18.5204,
            longitude=73.8567,
            location_name='TestRec_Incident_Wheelchair',
            has_disabled=True,
            accessibility_requirements='Wheelchair access required for 2 elderly residents'
        )
        eval_wc = evaluate_shelter_candidates(req_wheelchair, shelters=test_shelters)

        rej_ids_wc = [r['shelter'].id for r in eval_wc['rejected_shelters']]
        elig_ids_wc = [e['shelter'].id for e in eval_wc['eligible_shelters']]

        record_test("Shelter B (lacks wheelchair) is in rejected_shelters", sh_b.id in rej_ids_wc)
        record_test("Shelter B is NOT in eligible_shelters", sh_b.id not in elig_ids_wc)

        # Verify rejection reason mentions wheelchair
        b_rej = next(r for r in eval_wc['rejected_shelters'] if r['shelter'].id == sh_b.id)
        has_wc_reason = any('wheelchair' in r.lower() for r in b_rej['rejection_reasons'])
        record_test("Rejection reason explicitly states wheelchair absence", has_wc_reason)

        # 3.2 Medical Support Hard Exclusion
        # Request with injured people: Shelter C lacks medical -> MUST be excluded
        req_injured = ShelterRequest(
            submitted_by=admin_user.id,
            group_size=10,
            latitude=18.5204,
            longitude=73.8567,
            location_name='TestRec_Incident_Injured',
            injured_count=3,
            has_injured=True,
            medical_requirements='First aid and triage needed'
        )
        eval_inj = evaluate_shelter_candidates(req_injured, shelters=test_shelters)

        rej_ids_inj = [r['shelter'].id for r in eval_inj['rejected_shelters']]
        elig_ids_inj = [e['shelter'].id for e in eval_inj['eligible_shelters']]

        record_test("Shelter C (lacks medical) is in rejected_shelters", sh_c.id in rej_ids_inj)
        record_test("Shelter C is NOT in eligible_shelters", sh_c.id not in elig_ids_inj)

        c_rej = next(r for r in eval_inj['rejected_shelters'] if r['shelter'].id == sh_c.id)
        has_med_reason = any('medical' in r.lower() for r in c_rej['rejection_reasons'])
        record_test("Rejection reason explicitly states medical facility absence", has_med_reason)

        # 3.3 Inactive Shelter Exclusion
        # Inactive shelter D must be rejected in all queries
        record_test("Inactive Shelter D is in rejected_shelters", sh_d.id in rej_ids_wc)
        d_rej = next(r for r in eval_wc['rejected_shelters'] if r['shelter'].id == sh_d.id)
        record_test("Rejection reason states inactive status", any('active' in r.lower() or 'inactive' in r.lower() for r in d_rej['rejection_reasons']))

        # 3.4 Safe Capacity Hard Exclusion
        # Group size 20: Shelter E only has 5 safe spots available -> MUST be excluded
        req_capacity = ShelterRequest(
            submitted_by=admin_user.id,
            group_size=20,
            latitude=18.5204,
            longitude=73.8567,
            location_name='TestRec_Incident_Cap'
        )
        eval_cap = evaluate_shelter_candidates(req_capacity, shelters=test_shelters)
        rej_ids_cap = [r['shelter'].id for r in eval_cap['rejected_shelters']]
        record_test("Shelter E (safe capacity 5 < group size 20) is excluded", sh_e.id in rej_ids_cap)
        e_rej = next(r for r in eval_cap['rejected_shelters'] if r['shelter'].id == sh_e.id)
        record_test("Rejection reason mentions safe planning capacity", any('safe' in r.lower() and 'capacity' in r.lower() for r in e_rej['rejection_reasons']))

        print("\n" + "=" * 60)
        print("Suite 4: Explainability & Positive Reasons Generation")
        print("=" * 60)

        # Request requiring both wheelchair and medical for group of 15
        req_both = ShelterRequest(
            submitted_by=admin_user.id,
            group_size=15,
            latitude=18.5204,
            longitude=73.8567,
            location_name='TestRec_Incident_Both',
            has_disabled=True,
            has_injured=True,
            injured_count=2
        )
        db.session.add(req_both)
        db.session.commit()

        eval_both = evaluate_shelter_candidates(req_both, shelters=test_shelters)

        rec = eval_both['recommended_shelter']
        record_test("Recommended shelter exists", rec is not None)
        record_test("Shelter A is top recommended", rec['shelter'].id == sh_a.id)

        reasons = rec['positive_reasons']
        record_test("Positive reasons list is not empty", len(reasons) >= 3, f"Got: {reasons}")
        record_test("Reasons mention sufficient safe capacity", any('safe capacity' in r.lower() for r in reasons))
        record_test("Reasons mention medical facility available", any('medical facility' in r.lower() for r in reasons))
        record_test("Reasons mention wheelchair accessibility", any('wheelchair' in r.lower() for r in reasons))
        record_test("Reasons mention proximity", any('close' in r.lower() or 'km' in r.lower() for r in reasons))

        # Rejection audit exists and is transparent
        record_test("Total rejected shelters count is 4 (B, C, D, E)", eval_both['total_rejected'] == 4)
        record_test("Total eligible shelters count is 1 (A)", eval_both['total_eligible'] == 1)

        print("\n" + "=" * 60)
        print("Suite 5: Multiple End-to-End Scenarios")
        print("=" * 60)

        # 5.1 General Group (No special requirements, size 15)
        # B, C, A all have enough capacity; E has only 5 -> E rejected; D is inactive -> D rejected
        req_general = ShelterRequest(
            submitted_by=admin_user.id,
            group_size=15,
            latitude=18.5204,
            longitude=73.8567,
            location_name='TestRec_Incident_General'
        )
        eval_gen = evaluate_shelter_candidates(req_general, shelters=test_shelters)
        record_test("General group has 3 eligible shelters (A, B, C)", eval_gen['total_eligible'] == 3)
        record_test("Eligible shelters are ranked 1, 2, 3", [e['rank'] for e in eval_gen['eligible_shelters']] == [1, 2, 3])
        record_test("Top ranked shelter has highest total_score", eval_gen['eligible_shelters'][0]['total_score'] >= eval_gen['eligible_shelters'][1]['total_score'])

        # 5.2 Huge Group (Exceeding all safe capacities, size 1000)
        req_huge = ShelterRequest(
            submitted_by=admin_user.id,
            group_size=1000,
            latitude=18.5204,
            longitude=73.8567,
            location_name='TestRec_Incident_Huge'
        )
        eval_huge = evaluate_shelter_candidates(req_huge, shelters=test_shelters)
        record_test("Group of 1000 has 0 eligible single shelters", eval_huge['total_eligible'] == 0)
        record_test("Recommended shelter is None when 0 eligible", eval_huge['recommended_shelter'] is None)
        record_test("All 5 shelters listed in rejected_shelters", eval_huge['total_rejected'] == 5)

        # 5.3 Weight sensitivity: High distance weight vs High capacity weight
        # When distance is 90% weight, closer shelter gets higher score
        weights_dist = {'distance': 0.9, 'capacity': 0.05, 'facilities': 0.025, 'resources': 0.025}
        eval_w_dist = evaluate_shelter_candidates(req_general, shelters=test_shelters, custom_weights=weights_dist)
        record_test("Weights override accepted and normalized", abs(eval_w_dist['weights_used']['distance'] - 0.9) < 0.01)

        print("\n" + "=" * 60)
        print("Suite 6: HTTP Route Integration & Access Control")
        print("=" * 60)

        client = app.test_client()

        # 6.1 Unauthenticated access -> 302 redirect to login
        res_unauth = client.get('/recommend/')
        record_test("Unauthenticated GET /recommend/ -> 302 redirect", res_unauth.status_code == 302)

        # 6.2 Authenticate as field responder
        resp_user = User.query.filter_by(role='responder').first()
        if not resp_user:
            resp_user = User(email='responder_test@shelter.gov', full_name='Test Responder', role='responder')
            resp_user.set_password('Password@123')
            db.session.add(resp_user)
            db.session.commit()

        login_res = client.post('/auth/login', data={
            'email': resp_user.email,
            'password': 'Password@123'
        }, follow_redirects=True)
        record_test("Responder logged in successfully", login_res.status_code == 200)

        # 6.3 Form page loads with 200 OK
        res_form = client.get('/recommend/')
        record_test("GET /recommend/ returns 200 OK", res_form.status_code == 200)
        record_test("Page contains 'Shelter Recommendation Engine'", b'Shelter Recommendation Engine' in res_form.data)
        record_test("Page contains active weights overview", b'Active Scoring Weights' in res_form.data)

        # 6.4 Evaluate real request via route
        res_eval = client.get(f'/recommend/request/{req_both.id}')
        record_test(f"GET /recommend/request/{req_both.id} returns 200 OK", res_eval.status_code == 200)
        record_test("Results page shows Recommended Shelter (#1 Rank)", b'Recommended Shelter (#1 Rank)' in res_eval.data)
        record_test("Results page shows 'Why this shelter is recommended'", b'Why this shelter is recommended' in res_eval.data)
        record_test("Results page shows Excluded / Rejected Shelters", b'Excluded / Rejected Shelters' in res_eval.data)
        record_test("Results page contains mandatory disclaimer", b'not guaranteed to be optimal' in res_eval.data.lower())

        # 6.5 Simulation POST endpoint
        res_sim = client.post('/recommend/evaluate', data={
            'group_size': '35',
            'latitude': '18.5204',
            'longitude': '73.8567',
            'location_name': 'Simulation Test Zone',
            'has_disabled': '1',
            'injured_count': '1',
        }, follow_redirects=True)
        record_test("POST /recommend/evaluate simulation returns 200 OK", res_sim.status_code == 200)
        record_test("Simulation page displays simulation badge", b'Simulation Evaluation' in res_sim.data)

        # 6.6 API JSON endpoint
        res_api = client.get(f'/recommend/api/request/{req_both.id}')
        record_test("GET /recommend/api/request/<id> returns 200 OK", res_api.status_code == 200)
        api_data = res_api.get_json()
        record_test("API response contains recommended_shelter", api_data.get('recommended_shelter') is not None)
        record_test("API response contains positive_reasons", len(api_data['recommended_shelter']['positive_reasons']) > 0)
        record_test("API response contains disclaimer", 'disclaimer' in api_data)

        # Clean up created test records
        Shelter.query.filter(Shelter.name.like('TestRec_%')).delete(synchronize_session=False)
        ShelterRequest.query.filter(ShelterRequest.location_name.like('TestRec_%')).delete(synchronize_session=False)
        db.session.commit()

        print("\n" + "=" * 60)
        print(f"Total Tests Run: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print("=" * 60)

    return total_tests - passed_tests == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
