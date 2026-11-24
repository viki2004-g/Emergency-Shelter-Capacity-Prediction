"""
tests/test_allocation_transaction.py — Concurrency & Transactional Allocation Tests.

Tests the 8-Step ACID Transactional Allocation Pipeline:
  1. Start database transaction.
  2. Lock relevant shelter rows appropriately (SELECT ... FOR UPDATE).
  3. Re-check current safe capacity under lock.
  4. Verify the allocation is still valid.
  5. Create allocation records (confirmed=True).
  6. Update shelter occupancy.
  7. Create occupancy history records.
  8. Commit the transaction.
  - ROLLBACK on any failure.
  - Prevention of over-allocation under concurrent responder load.

Test Matrix:
  Suite 1: Successful Allocation (Single Shelter)
  Suite 2: Insufficient Capacity (Safe Limit Overrun & Rollback)
  Suite 3: Failed Transaction (Rollback Guarantee & Zero Partial State)
  Suite 4: Multiple Shelters (Atomic Split Allocation & Atomic Abort)
  Suite 5: Total Allocated != Requested Group Size (Mismatch Rejection)
  Suite 6: Concurrency Protection (Multithreaded Race Condition & Row-Locking)
  Suite 7: HTTP Routes for Allocation Confirmation
"""

import os
import sys
import threading
import time
from unittest.mock import patch

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db, bcrypt
from models.allocation import Allocation
from models.facility import ShelterFacility
from models.occupancy import OccupancyHistory
from models.request import ShelterRequest
from models.resource import Resource
from models.shelter import Shelter
from models.user import User

from services.allocation import (
    confirm_allocation,
    AllocationError,
    InsufficientCapacityError,
    InvalidAllocationError,
    GroupSizeMismatchError,
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
        print(f"  [FAIL] {name} -- {detail}")


def _cleanup_test_records():
    """Wipes test shelters, requests, allocations, and history cleanly."""
    with app.app_context():
        # Find test shelter and request IDs
        sh_ids = [s.id for s in Shelter.query.filter(Shelter.name.like('TestAlloc_%')).all()]
        req_ids = [r.id for r in ShelterRequest.query.filter(ShelterRequest.location_name.like('TestAlloc_%')).all()]

        if req_ids:
            Allocation.query.filter(Allocation.request_id.in_(req_ids)).delete(synchronize_session=False)
        if sh_ids:
            Allocation.query.filter(Allocation.shelter_id.in_(sh_ids)).delete(synchronize_session=False)
            OccupancyHistory.query.filter(OccupancyHistory.shelter_id.in_(sh_ids)).delete(synchronize_session=False)
            ShelterFacility.query.filter(ShelterFacility.shelter_id.in_(sh_ids)).delete(synchronize_session=False)
            Resource.query.filter(Resource.shelter_id.in_(sh_ids)).delete(synchronize_session=False)
            Shelter.query.filter(Shelter.id.in_(sh_ids)).delete(synchronize_session=False)
        if req_ids:
            ShelterRequest.query.filter(ShelterRequest.id.in_(req_ids)).delete(synchronize_session=False)
        db.session.commit()


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 1: Successful Allocation (Single Shelter)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    _cleanup_test_records()

    user = User.query.filter_by(role='admin').first()
    if not user:
        user = User(
            email='admin@shelter.gov',
            full_name='System Admin',
            role='admin',
            password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8')
        )
        db.session.add(user)
        db.session.commit()

    # Max = 100, Safe Limit = 80% (Safe Capacity = 80), Current Occ = 20 -> Safe Avail = 60
    s1 = Shelter(
        name='TestAlloc_S1', address='Road 1', latitude=18.52, longitude=73.85,
        max_capacity=100, current_occupancy=20, status='active', safe_limit_pct=80
    )
    db.session.add(s1)
    db.session.flush()

    req1 = ShelterRequest(
        submitted_by=user.id,
        group_size=25,
        latitude=18.52,
        longitude=73.85,
        location_name='TestAlloc_Loc1',
        status='pending'
    )
    db.session.add(req1)
    db.session.commit()

    # Execute confirmation
    res = confirm_allocation(
        request_id=req1.id,
        allocations=[{'shelter_id': s1.id, 'allocated_count': 25}],
        confirmed_by_user_id=user.id,
        notes="Test single shelter placement"
    )

    record("Return dictionary reports success = True", res.get('success') is True)
    record("Return dictionary reports total_allocated = 25", res.get('total_allocated') == 25)
    record("Return dictionary contains allocations list", len(res.get('allocations', [])) == 1)

    # Refresh objects from DB to verify persistence
    db.session.refresh(s1)
    db.session.refresh(req1)

    record("Shelter current_occupancy incremented (20 -> 45)", s1.current_occupancy == 45)
    record("Shelter safe_available_capacity updated (60 -> 35)", s1.safe_available_capacity == 35)
    record("ShelterRequest status updated from 'pending' to 'allocated'", req1.status == 'allocated')

    # Verify persisted Allocation record
    alloc = Allocation.query.filter_by(request_id=req1.id, shelter_id=s1.id).first()
    record("Allocation record persisted in database", alloc is not None)
    record("Allocation record confirmed = True", alloc and alloc.confirmed is True)
    record("Allocation record count == 25", alloc and alloc.allocated_count == 25)
    record("Allocation confirmed_by matches user", alloc and alloc.confirmed_by == user.id)

    # Verify immutable OccupancyHistory entry
    hist = (
        OccupancyHistory.query
        .filter_by(shelter_id=s1.id)
        .order_by(OccupancyHistory.recorded_at.desc())
        .first()
    )
    record("OccupancyHistory record created", hist is not None)
    record("OccupancyHistory recorded occupancy == 45", hist and hist.occupancy == 45)
    record("OccupancyHistory recorded_by matches user", hist and hist.recorded_by == user.id)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 2: Insufficient Capacity (Safe Limit Overrun & Rollback)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    # Shelter Max = 100, Safe Limit = 80%, Current Occ = 60 -> Safe Avail = 20
    s2 = Shelter(
        name='TestAlloc_S2', address='Road 2', latitude=18.53, longitude=73.86,
        max_capacity=100, current_occupancy=60, status='active', safe_limit_pct=80
    )
    db.session.add(s2)
    db.session.flush()

    # Request requires 30 (exceeds safe available capacity of 20)
    req2 = ShelterRequest(
        submitted_by=user.id,
        group_size=30,
        latitude=18.53,
        longitude=73.86,
        location_name='TestAlloc_Loc2',
        status='pending'
    )
    db.session.add(req2)
    db.session.commit()

    initial_occ = s2.current_occupancy
    initial_status = req2.status

    caught_insufficient = False
    try:
        confirm_allocation(
            request_id=req2.id,
            allocations=[{'shelter_id': s2.id, 'allocated_count': 30}],
            confirmed_by_user_id=user.id
        )
    except InsufficientCapacityError as err:
        caught_insufficient = True
        record("Raises InsufficientCapacityError on capacity breach", True)
        record("Error message mentions needed (30) and safe available (20)",
               '30' in str(err) and '20' in str(err))

    record("InsufficientCapacityError was caught", caught_insufficient)

    # Verify transaction rollback
    db.session.refresh(s2)
    db.session.refresh(req2)

    record("Rollback: Shelter occupancy unchanged (remains 60)", s2.current_occupancy == initial_occ)
    record("Rollback: Request status unchanged (remains 'pending')", req2.status == initial_status)

    alloc_count = Allocation.query.filter_by(request_id=req2.id).count()
    record("Rollback: Zero Allocation records persisted", alloc_count == 0)

    hist_count = OccupancyHistory.query.filter_by(shelter_id=s2.id).count()
    record("Rollback: Zero OccupancyHistory records persisted", hist_count == 0)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 3: Failed Transaction (Rollback Guarantee & Zero Partial State)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    s3 = Shelter(
        name='TestAlloc_S3', address='Road 3', latitude=18.54, longitude=73.87,
        max_capacity=100, current_occupancy=10, status='active', safe_limit_pct=80
    )
    db.session.add(s3)
    db.session.flush()

    req3 = ShelterRequest(
        submitted_by=user.id,
        group_size=15,
        latitude=18.54,
        longitude=73.87,
        location_name='TestAlloc_Loc3',
        status='pending'
    )
    db.session.add(req3)
    db.session.commit()

    initial_occ3 = s3.current_occupancy

    # Simulate mid-transaction crash right before commit
    simulated_failure_caught = False
    with patch.object(db.session, 'commit', side_effect=RuntimeError("Simulated Database I/O Crash")):
        try:
            confirm_allocation(
                request_id=req3.id,
                allocations=[{'shelter_id': s3.id, 'allocated_count': 15}],
                confirmed_by_user_id=user.id
            )
        except RuntimeError as r_err:
            if "Simulated Database I/O Crash" in str(r_err):
                simulated_failure_caught = True

    record("Simulated crash triggers exception and rollback handler", simulated_failure_caught)

    # Verify rollback
    db.session.rollback()  # Clear local session
    s3_refreshed = db.session.get(Shelter, s3.id)
    req3_refreshed = db.session.get(ShelterRequest, req3.id)

    record("Rollback on crash: Shelter occupancy remains unchanged (10)", s3_refreshed.current_occupancy == initial_occ3)
    record("Rollback on crash: Request status remains 'pending'", req3_refreshed.status == 'pending')

    alloc_orphans = Allocation.query.filter_by(request_id=req3.id).count()
    record("Rollback on crash: Zero orphaned Allocation records", alloc_orphans == 0)

    hist_orphans = OccupancyHistory.query.filter_by(shelter_id=s3.id).count()
    record("Rollback on crash: Zero orphaned OccupancyHistory records", hist_orphans == 0)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 4: Multiple Shelters (Atomic Split Allocation & Atomic Abort)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    # 3 Shelters with safe capacities:
    # m1: max 100, occ 50 -> safe avail = 30. Allocate 20.
    # m2: max 100, occ 55 -> safe avail = 25. Allocate 25.
    # m3: max 100, occ 65 -> safe avail = 15. Allocate 15.
    # Total group size = 20 + 25 + 15 = 60.
    m1 = Shelter(name='TestAlloc_M1', address='Loc M1', latitude=18.51, longitude=73.81,
                 max_capacity=100, current_occupancy=50, status='active', safe_limit_pct=80)
    m2 = Shelter(name='TestAlloc_M2', address='Loc M2', latitude=18.52, longitude=73.82,
                 max_capacity=100, current_occupancy=55, status='active', safe_limit_pct=80)
    m3 = Shelter(name='TestAlloc_M3', address='Loc M3', latitude=18.53, longitude=73.83,
                 max_capacity=100, current_occupancy=65, status='active', safe_limit_pct=80)
    db.session.add_all([m1, m2, m3])
    db.session.flush()

    req4 = ShelterRequest(
        submitted_by=user.id,
        group_size=60,
        latitude=18.51,
        longitude=73.81,
        location_name='TestAlloc_Loc4',
        status='pending'
    )
    db.session.add(req4)
    db.session.commit()

    # Pass in intentionally reverse-sorted shelter IDs to verify sorting & deadlock avoidance
    multi_plan = [
        {'shelter_id': m3.id, 'allocated_count': 15},
        {'shelter_id': m1.id, 'allocated_count': 20},
        {'shelter_id': m2.id, 'allocated_count': 25},
    ]

    res_multi = confirm_allocation(
        request_id=req4.id,
        allocations=multi_plan,
        confirmed_by_user_id=user.id,
        notes="Atomic multi-shelter redistribution confirmation"
    )

    record("Multi-shelter allocation confirmed successfully", res_multi['success'] is True)
    record("Total allocated across 3 shelters == 60", res_multi['total_allocated'] == 60)
    record("Shelters updated list contains 3 IDs in sorted order",
           res_multi['shelters_updated'] == sorted([m1.id, m2.id, m3.id]))

    # Verify all 3 occupancies updated
    db.session.refresh(m1)
    db.session.refresh(m2)
    db.session.refresh(m3)
    db.session.refresh(req4)

    record("Shelter M1 occupancy updated (50 + 20 = 70)", m1.current_occupancy == 70)
    record("Shelter M2 occupancy updated (55 + 25 = 80)", m2.current_occupancy == 80)
    record("Shelter M3 occupancy updated (65 + 15 = 80)", m3.current_occupancy == 80)
    record("Request marked 'allocated'", req4.status == 'allocated')

    alloc_records = Allocation.query.filter_by(request_id=req4.id).all()
    record("Created 3 confirmed Allocation records", len(alloc_records) == 3)
    record("All 3 Allocation records have confirmed = True", all(a.confirmed for a in alloc_records))

    # Test ATOMIC ABORT when one shelter in a multi-shelter plan fails
    # Create new request of 30, trying to allocate 10 to M1 (OK) and 20 to M2 (exceeds M2 safe capacity: 0 left)
    req4_fail = ShelterRequest(
        submitted_by=user.id,
        group_size=30,
        latitude=18.51,
        longitude=73.81,
        location_name='TestAlloc_Loc4_Fail',
        status='pending'
    )
    db.session.add(req4_fail)
    db.session.commit()

    occ_before_m1 = m1.current_occupancy
    occ_before_m2 = m2.current_occupancy

    multi_plan_fail = [
        {'shelter_id': m1.id, 'allocated_count': 10},
        {'shelter_id': m2.id, 'allocated_count': 20},  # M2 is already at 80/80 safe capacity!
    ]

    caught_multi_abort = False
    try:
        confirm_allocation(req4_fail.id, multi_plan_fail, confirmed_by_user_id=user.id)
    except InsufficientCapacityError:
        caught_multi_abort = True

    record("Multi-shelter plan aborts when one shelter lacks capacity", caught_multi_abort)

    db.session.refresh(m1)
    db.session.refresh(m2)
    db.session.refresh(req4_fail)

    record("Atomic abort: Shelter M1 occupancy NOT partially modified", m1.current_occupancy == occ_before_m1)
    record("Atomic abort: Shelter M2 occupancy NOT modified", m2.current_occupancy == occ_before_m2)
    record("Atomic abort: Request status remains 'pending'", req4_fail.status == 'pending')
    record("Atomic abort: Zero Allocation records created for failed request",
           Allocation.query.filter_by(request_id=req4_fail.id).count() == 0)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 5: Total Allocated != Requested Group Size (Mismatch Rejection)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    s5 = Shelter(
        name='TestAlloc_S5', address='Road 5', latitude=18.55, longitude=73.88,
        max_capacity=100, current_occupancy=10, status='active', safe_limit_pct=80
    )
    db.session.add(s5)
    db.session.flush()

    req5 = ShelterRequest(
        submitted_by=user.id,
        group_size=50,
        latitude=18.55,
        longitude=73.88,
        location_name='TestAlloc_Loc5',
        status='pending'
    )
    db.session.add(req5)
    db.session.commit()

    initial_occ5 = s5.current_occupancy

    # Test Under-Allocation (allocated 30 < requested 50)
    caught_under = False
    try:
        confirm_allocation(
            request_id=req5.id,
            allocations=[{'shelter_id': s5.id, 'allocated_count': 30}],
            confirmed_by_user_id=user.id
        )
    except GroupSizeMismatchError as err:
        caught_under = True
        record("Under-allocation raises GroupSizeMismatchError", True)
        record("Error message explains mismatch (30 vs 50)", '30' in str(err) and '50' in str(err))

    record("Under-allocation was rejected", caught_under)

    # Test Over-Allocation (allocated 70 > requested 50)
    caught_over = False
    try:
        confirm_allocation(
            request_id=req5.id,
            allocations=[{'shelter_id': s5.id, 'allocated_count': 70}],
            confirmed_by_user_id=user.id
        )
    except GroupSizeMismatchError as err:
        caught_over = True
        record("Over-allocation raises GroupSizeMismatchError", True)
        record("Error message explains mismatch (70 vs 50)", '70' in str(err) and '50' in str(err))

    record("Over-allocation was rejected", caught_over)

    # Verify state remains completely untouched
    db.session.refresh(s5)
    db.session.refresh(req5)
    record("Mismatch rejection: Shelter occupancy untouched (10)", s5.current_occupancy == initial_occ5)
    record("Mismatch rejection: Request status remains 'pending'", req5.status == 'pending')
    record("Mismatch rejection: Zero allocations persisted",
           Allocation.query.filter_by(request_id=req5.id).count() == 0)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 6: Concurrency Protection (Race Condition & Pessimistic Locking)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    # Shelter Max = 100, Safe Limit = 80% (Safe Capacity = 80), Current Occ = 65.
    # Real-time Safe Available Capacity = 80 - 65 = 15.
    # Two separate response teams (Team A and Team B) each try to allocate 10 people at the same time.
    # 10 + 10 = 20 > 15 available.
    # WITHOUT locking: both would read 15, both would succeed -> occupancy becomes 85 (OVER-ALLOCATION!).
    # WITH pessimistic locking (SELECT ... FOR UPDATE):
    #   Thread 1 acquires lock, verifies 10 <= 15 -> succeeds, commits (occupancy -> 75, safe avail -> 5).
    #   Thread 2 waits on the lock. Once unlocked, it re-checks capacity under lock:
    #   safe available is now 5 < 10 -> raises InsufficientCapacityError, rolls back!
    #   Final occupancy is 75. ZERO OVER-ALLOCATION!

    s_race = Shelter(
        name='TestAlloc_Race', address='Race Track', latitude=18.56, longitude=73.89,
        max_capacity=100, current_occupancy=65, status='active', safe_limit_pct=80
    )
    db.session.add(s_race)
    db.session.flush()

    req_team_a = ShelterRequest(
        submitted_by=user.id,
        group_size=10,
        latitude=18.56,
        longitude=73.89,
        location_name='TestAlloc_Race_A',
        status='pending'
    )
    req_team_b = ShelterRequest(
        submitted_by=user.id,
        group_size=10,
        latitude=18.56,
        longitude=73.89,
        location_name='TestAlloc_Race_B',
        status='pending'
    )
    db.session.add_all([req_team_a, req_team_b])
    db.session.commit()

    s_race_id = s_race.id
    req_a_id = req_team_a.id
    req_b_id = req_team_b.id
    user_id = user.id

    # Detach main thread session so each worker thread acquires its own clean connection
    db.session.remove()

    thread_results = {}
    barrier = threading.Barrier(2)

    def responder_team_a():
        with app.app_context():
            barrier.wait()  # synchronize concurrent release
            try:
                res_a = confirm_allocation(
                    request_id=req_a_id,
                    allocations=[{'shelter_id': s_race_id, 'allocated_count': 10}],
                    confirmed_by_user_id=user_id,
                    notes="Team A allocation"
                )
                thread_results['team_a'] = ('SUCCESS', res_a['total_allocated'])
            except Exception as e:
                thread_results['team_a'] = ('ERROR', type(e).__name__, str(e))
            finally:
                db.session.remove()

    def responder_team_b():
        with app.app_context():
            barrier.wait()  # synchronize concurrent release
            try:
                res_b = confirm_allocation(
                    request_id=req_b_id,
                    allocations=[{'shelter_id': s_race_id, 'allocated_count': 10}],
                    confirmed_by_user_id=user_id,
                    notes="Team B allocation"
                )
                thread_results['team_b'] = ('SUCCESS', res_b['total_allocated'])
            except Exception as e:
                thread_results['team_b'] = ('ERROR', type(e).__name__, str(e))
            finally:
                db.session.remove()

    t_a = threading.Thread(target=responder_team_a)
    t_b = threading.Thread(target=responder_team_b)

    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    # Inspect results from both threads
    statuses = [thread_results['team_a'][0], thread_results['team_b'][0]]
    record("Concurrency: Exactly one thread succeeded", statuses.count('SUCCESS') == 1,
           f"Results: {thread_results}")
    record("Concurrency: Exactly one thread failed", statuses.count('ERROR') == 1,
           f"Results: {thread_results}")

    # The failing thread must have failed with InsufficientCapacityError
    failing_thread = 'team_a' if thread_results['team_a'][0] == 'ERROR' else 'team_b'
    fail_err_type = thread_results[failing_thread][1]
    record("Concurrency: Failing thread caught InsufficientCapacityError",
           fail_err_type == 'InsufficientCapacityError', f"Caught: {fail_err_type}")

    # Inspect database state by loading fresh instances
    s_race = db.session.get(Shelter, s_race_id)
    record("Concurrency: Final shelter occupancy is exactly 75 (never 85)",
           s_race.current_occupancy == 75, f"Actual occupancy: {s_race.current_occupancy}")
    record("Concurrency: Final safe available capacity is 5 >= 0",
           s_race.safe_available_capacity == 5)
    record("Concurrency: Shelter safe capacity boundary (80) was NOT breached",
           s_race.current_occupancy <= s_race.safe_capacity)

    # Inspect request states
    req_team_a = db.session.get(ShelterRequest, req_a_id)
    req_team_b = db.session.get(ShelterRequest, req_b_id)
    req_statuses = [req_team_a.status, req_team_b.status]
    record("Concurrency: Exactly one request marked 'allocated'", req_statuses.count('allocated') == 1)
    record("Concurrency: Exactly one request remains 'pending'", req_statuses.count('pending') == 1)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 7: HTTP Routes & Transaction Confirmation Interface")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    admin_user = User.query.filter_by(role='admin').first()

    # Create shelter & request for HTTP test
    s_http = Shelter(
        name='TestAlloc_HTTP', address='HTTP Road', latitude=18.52, longitude=73.85,
        max_capacity=100, current_occupancy=10, status='active', safe_limit_pct=80
    )
    db.session.add(s_http)
    db.session.flush()

    req_http = ShelterRequest(
        submitted_by=admin_user.id,
        group_size=15,
        latitude=18.52,
        longitude=73.85,
        location_name='TestAlloc_HTTP_Loc',
        status='pending'
    )
    db.session.add(req_http)
    db.session.commit()

    # 7.1 Unauthenticated POST /recommend/confirm/<id> -> 302 to login
    client_unauth = app.test_client()
    res_unauth = client_unauth.post(f'/recommend/confirm/{req_http.id}', data={'shelter_id': s_http.id})
    record("Unauthenticated POST /recommend/confirm/<id> redirects to login (302)",
           res_unauth.status_code == 302 and '/auth/login' in res_unauth.headers.get('Location', ''))

    # Verify that unauthenticated attempt did NOT mutate request or shelter
    db.session.refresh(req_http)
    db.session.refresh(s_http)
    record("Unauthenticated attempt did not alter request status", req_http.status == 'pending')
    record("Unauthenticated attempt did not alter shelter occupancy", s_http.current_occupancy == 10)

    # 7.2 Authenticated Client Login
    client = app.test_client()
    login_res = client.post('/auth/login', data={
        'email': admin_user.email,
        'password': 'Password@123'
    }, follow_redirects=True)
    record("Admin login successful for HTTP test client", login_res.status_code == 200)

    # 7.3 Authenticated POST /recommend/confirm/<id> -> executes allocation & redirects with success flash
    res_confirm = client.post(f'/recommend/confirm/{req_http.id}', data={
        'shelter_id': s_http.id,
        'notes': 'HTTP confirmation test'
    }, follow_redirects=True)

    confirm_html = res_confirm.data.decode('utf-8', errors='replace')
    has_flash = ('Allocation confirmed!' in confirm_html or 'successfully placed' in confirm_html)
    record("Authenticated POST /recommend/confirm/<id> returns 200 OK after redirect", res_confirm.status_code == 200)
    record("Success flash message displayed in HTML", has_flash)

    db.session.refresh(s_http)
    db.session.refresh(req_http)
    record("HTTP Confirmation: Shelter occupancy updated (10 + 15 = 25)", s_http.current_occupancy == 25)
    record("HTTP Confirmation: Request status updated to 'allocated'", req_http.status == 'allocated')

    # 7.4 POST /recommend/confirm/<id> when request already allocated -> flash warning
    res_double = client.post(f'/recommend/confirm/{req_http.id}', data={
        'shelter_id': s_http.id
    }, follow_redirects=True)
    double_html = res_double.data.decode('utf-8', errors='replace')
    record("Confirming already allocated request is rejected with message",
           'already been fully allocated' in double_html or 'already marked as \'allocated\'' in double_html)

    # Final cleanup of all test records
    _cleanup_test_records()


# =============================================================================
print("\n" + "=" * 64)
print(f"Total Tests Run : {total_tests}")
print(f"Passed          : {passed_tests}")
print(f"Failed          : {total_tests - passed_tests}")
print("=" * 64)

if __name__ == '__main__':
    sys.exit(0 if total_tests == passed_tests else 1)
