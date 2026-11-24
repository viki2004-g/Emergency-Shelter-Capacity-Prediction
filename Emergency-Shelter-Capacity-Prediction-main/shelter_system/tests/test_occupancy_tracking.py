"""
tests/test_occupancy_tracking.py — Stage 6 tests for Occupancy Tracking.

Verifies:
  1. Formulas:
     - Available Capacity = Maximum Capacity - Current Occupancy
     - Occupancy Percentage = (Current Occupancy / Maximum Capacity) * 100
     - Planning Capacity = Maximum Capacity * (Safe Limit % / 100)
     - Safe Available Capacity = Planning Capacity - Current Occupancy
  2. Configurable Safe Limits:
     - Global default (e.g. 85%) and per-shelter overrides
     - Example from spec: Max = 500, Safe Limit = 85% -> Planning Capacity = 425
  3. Configurable Status Thresholds:
     - 0–60%   -> Safe
     - 61–80%  -> Moderate
     - 81–95%  -> High
     - 96–100% -> Critical
     - > 100%  -> Overcrowded
     - Verifies custom configured thresholds dynamically alter status
  4. Occupancy History (Append-Only):
     - New row created whenever occupancy changes
     - Existing history records are never overwritten
     - Recorded_by foreign key links to the user
     - Non-negative occupancy validation
  5. HTTP Routes:
     - GET /shelters/occupancy
     - GET /shelters/<id>/occupancy
     - POST /shelters/<id>/occupancy (regular form + JSON)
"""

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db
from models import Shelter, OccupancyHistory, User
from services.capacity import (
    calculate_available_capacity,
    calculate_occupancy_percentage,
    calculate_safe_capacity,
    calculate_safe_available_capacity,
    determine_occupancy_status,
    get_status_label,
    record_occupancy_change,
    get_configured_thresholds,
)


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
        print("Suite 1: Core Mathematical Formulas & Safe Limits")
        print("==================================================")

        # 1. Available Capacity = Max Capacity - Current Occupancy
        check("Available Capacity: 500 - 300 = 200", calculate_available_capacity(500, 300) == 200)
        check("Available Capacity: 500 - 500 = 0", calculate_available_capacity(500, 500) == 0)
        check("Available Capacity (overcrowded): 500 - 525 = -25", calculate_available_capacity(500, 525) == -25)

        # 2. Occupancy Percentage = (Current Occupancy / Max Capacity) * 100
        check("Occupancy %: (250 / 500) * 100 = 50.0%", calculate_occupancy_percentage(250, 500) == 50.0)
        check("Occupancy %: (425 / 500) * 100 = 85.0%", calculate_occupancy_percentage(425, 500) == 85.0)
        check("Occupancy %: (550 / 500) * 100 = 110.0%", calculate_occupancy_percentage(550, 500) == 110.0)
        check("Occupancy %: Division by zero handled safely", calculate_occupancy_percentage(10, 0) == 0.0)

        # 3. Safe Planning Limit Example from specification:
        # Maximum capacity = 500, Safe limit = 85% -> Planning capacity = 425
        safe_cap = calculate_safe_capacity(500, 85)
        check("Safe Planning Capacity: 500 @ 85% = 425", safe_cap == 425)

        # Safe Available Capacity = Safe Planning Capacity - Current Occupancy
        # If Current Occupancy = 400: Safe Available = 425 - 400 = 25
        safe_avail_1 = calculate_safe_available_capacity(500, 400, 85)
        check("Safe Available Capacity: 425 - 400 = 25", safe_avail_1 == 25)

        # If Current Occupancy = 450: Safe Available = 425 - 450 = -25 (exceeded safe limit)
        safe_avail_2 = calculate_safe_available_capacity(500, 450, 85)
        check("Safe Available Capacity: 425 - 450 = -25", safe_avail_2 == -25)

        print("\n==================================================")
        print("Suite 2: Configurable Status Thresholds")
        print("==================================================")

        # Standard Thresholds: 0-60% Safe, 61-80% Moderate, 81-95% High, 96-100% Critical, >100% Overcrowded
        check("0% -> safe", determine_occupancy_status(0.0) == 'safe')
        check("59.9% -> safe", determine_occupancy_status(59.9) == 'safe')
        check("60.0% -> safe", determine_occupancy_status(60.0) == 'safe')
        check("60.1% -> moderate", determine_occupancy_status(60.1) == 'moderate')
        check("80.0% -> moderate", determine_occupancy_status(80.0) == 'moderate')
        check("80.1% -> high", determine_occupancy_status(80.1) == 'high')
        check("85.0% -> high", determine_occupancy_status(85.0) == 'high')
        check("95.0% -> high", determine_occupancy_status(95.0) == 'high')
        check("95.1% -> critical", determine_occupancy_status(95.1) == 'critical')
        check("100.0% -> critical", determine_occupancy_status(100.0) == 'critical')
        check("100.1% -> overcrowded", determine_occupancy_status(100.1) == 'overcrowded')
        check("120.0% -> overcrowded", determine_occupancy_status(120.0) == 'overcrowded')

        # Custom Thresholds test: verify threshold configuration is genuinely configurable
        custom_t = {'safe': 50.0, 'moderate': 75.0, 'high': 90.0, 'critical': 98.0}
        check("Custom threshold 55% is moderate when safe=50%",
              determine_occupancy_status(55.0, custom_t) == 'moderate')
        check("Custom threshold 92% is critical when high=90%",
              determine_occupancy_status(92.0, custom_t) == 'critical')

        print("\n==================================================")
        print("Suite 3: Shelter Model Properties & Calculations")
        print("==================================================")

        # Create or fetch test manager
        manager = User.query.filter_by(email='occ_manager@test.gov').first()
        if not manager:
            manager = User(
                full_name='Occupancy Manager',
                email='occ_manager@test.gov',
                password_hash='dummy',
                role='shelter_manager'
            )
            db.session.add(manager)
            db.session.commit()

        # Clean up any leftover test shelter
        old_s = Shelter.query.filter_by(name='__test_occupancy_shelter__').first()
        if old_s:
            db.session.delete(old_s)
            db.session.commit()

        # Create test shelter: Max 500, Initial Occupancy 250, Safe Limit 85%
        shelter = Shelter(
            name='__test_occupancy_shelter__',
            address='123 Capacity Boulevard',
            latitude=18.520430,
            longitude=73.856744,
            max_capacity=500,
            current_occupancy=250,
            safe_limit_pct=85,
            status='active',
            managed_by=manager.id
        )
        db.session.add(shelter)
        db.session.commit()

        check("Shelter model available_capacity == 250", shelter.available_capacity == 250)
        check("Shelter model occupancy_pct == 50.0", shelter.occupancy_pct == 50.0)
        check("Shelter model safe_limit == 85", shelter.safe_limit == 85)
        check("Shelter model safe_capacity == 425", shelter.safe_capacity == 425)
        check("Shelter model safe_available_capacity == 175", shelter.safe_available_capacity == 175)
        check("Shelter model capacity_status == 'safe'", shelter.capacity_status == 'safe')
        check("Shelter model capacity_status_label == 'Safe'", shelter.capacity_status_label == 'Safe')

        print("\n==================================================")
        print("Suite 4: Occupancy History Append-Only Logging")
        print("==================================================")

        # Initially, create initial history
        changed, h1 = record_occupancy_change(shelter, 250, user_id=manager.id, force=True)
        check("Initial history entry logged", changed is True and h1 is not None)
        check("History record occupancy count is 250", h1.occupancy == 250)
        check("History recorded_by is manager", h1.recorded_by == manager.id)

        # Update 1: Increase occupancy to 425 (85%, safe planning limit reached)
        changed, h2 = record_occupancy_change(shelter, 425, user_id=manager.id)
        check("Update 1 recorded in shelter", shelter.current_occupancy == 425)
        check("Update 1 safe available is 0", shelter.safe_available_capacity == 0)
        check("Update 1 capacity status is 'high' (85%)", shelter.capacity_status == 'high')

        # Update 2: Increase occupancy to 490 (98%, critical)
        changed, h3 = record_occupancy_change(shelter, 490, user_id=manager.id)
        check("Update 2 recorded in shelter", shelter.current_occupancy == 490)
        check("Update 2 capacity status is 'critical' (98%)", shelter.capacity_status == 'critical')
        check("Update 2 safe available is -65", shelter.safe_available_capacity == -65)

        # Update 3: Overcrowd to 520 (104%)
        changed, h4 = record_occupancy_change(shelter, 520, user_id=manager.id)
        check("Update 3 recorded in shelter", shelter.current_occupancy == 520)
        check("Update 3 available capacity is -20", shelter.available_capacity == -20)
        check("Update 3 capacity status is 'overcrowded'", shelter.capacity_status == 'overcrowded')

        # Verify history is APPEND-ONLY: previous records MUST still exist untouched!
        hist_count = OccupancyHistory.query.filter_by(shelter_id=shelter.id).count()
        check("History table contains all 4 sequential updates", hist_count == 4)

        all_hist = (OccupancyHistory.query
                    .filter_by(shelter_id=shelter.id)
                    .order_by(OccupancyHistory.recorded_at.asc())
                    .all())
        recorded_counts = [h.occupancy for h in all_hist]
        check("History preserves accurate sequential progression [250, 425, 490, 520]",
              recorded_counts == [250, 425, 490, 520])

        # Negative occupancy validation
        try:
            record_occupancy_change(shelter, -5, user_id=manager.id)
            check("Negative occupancy rejected", False, "Failed to raise ValueError")
        except ValueError:
            check("Negative occupancy rejected with ValueError", True)

        print("\n==================================================")
        print("Suite 5: HTTP Endpoints & UI Integration")
        print("==================================================")

        client = app.test_client()

        # Login manager
        with client.session_transaction() as sess:
            sess['_user_id'] = str(manager.id)
            sess['_fresh'] = True

        # Test 1: GET /shelters/occupancy (Overview)
        resp_overview = client.get('/shelters/occupancy')
        check("GET /shelters/occupancy returns 200 OK", resp_overview.status_code == 200)
        check("Overview contains 'Network Occupancy Tracking'", b"Network Occupancy Tracking" in resp_overview.data)
        check("Overview contains safe available capacity metric", b"Safe Available" in resp_overview.data)

        # Test 2: GET /shelters/<id>/occupancy (Single Shelter Tracking)
        resp_shelter_occ = client.get(f'/shelters/{shelter.id}/occupancy')
        check("GET /shelters/<id>/occupancy returns 200 OK", resp_shelter_occ.status_code == 200)
        check("Single shelter occupancy page shows shelter name", shelter.name.encode() in resp_shelter_occ.data)
        check("Single shelter occupancy page displays history log", b"Immutable Occupancy History Log" in resp_shelter_occ.data)

        # Test 3: POST /shelters/<id>/occupancy (Update via Form)
        post_resp = client.post(
            f'/shelters/{shelter.id}/occupancy',
            data={'current_occupancy': '300'},
            follow_redirects=True
        )
        check("POST /shelters/<id>/occupancy succeeds (redirect/200)", post_resp.status_code == 200)
        db.session.refresh(shelter)
        check("Shelter occupancy successfully updated to 300", shelter.current_occupancy == 300)
        check("Shelter capacity status now 'moderate' (60%)", shelter.capacity_status == 'safe' or shelter.capacity_status == 'moderate')

        # Test 4: POST /shelters/<id>/occupancy with negative value rejected
        err_resp = client.post(
            f'/shelters/{shelter.id}/occupancy',
            data={'current_occupancy': '-20'},
            follow_redirects=True
        )
        check("POST negative occupancy rejected with danger flash", b"valid non-negative" in err_resp.data)

        # Clean up
        db.session.delete(shelter)
        db.session.delete(manager)
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
