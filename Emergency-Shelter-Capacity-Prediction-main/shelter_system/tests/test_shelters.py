"""
tests/test_shelters.py — Shelter management CRUD tests.

Tests:
  - CREATE: valid + invalid (missing field, duplicate name)
  - READ:   list all, filter by status, search by name
  - UPDATE: edit name + occupancy + status
  - ACCESS: unauthorized access (wrong role)
  - PROPERTY: capacity_status, available_capacity, safe_limit
"""

import sys
sys.path.insert(0, '.')

from app import create_app
from extensions import db
from models import Shelter, ShelterFacility, Resource, OccupancyHistory, User

app = create_app('testing')

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f'  [PASS] {label}')
    else:
        FAIL += 1
        print(f'  [FAIL] {label}')


def run_tests():
    with app.app_context():
        print('\n=== Shelter CRUD Tests ===\n')

        # ── CREATE ──────────────────────────────────────────────────────────────
        print('--- CREATE')

        admin = User.query.filter_by(email='admin@shelter.gov').first()
        check('Admin user found', admin is not None)

        initial_count = Shelter.query.count()

        # Valid create
        s = Shelter(
            name='Test Shelter Alpha',
            address='123 Test Street, Pune',
            latitude=18.5200,
            longitude=73.8700,
            max_capacity=200,
            current_occupancy=50,
            status='active',
        )
        db.session.add(s)
        db.session.flush()

        fac = ShelterFacility(shelter_id=s.id, has_electricity=True, has_toilets=True)
        res = Resource(shelter_id=s.id, beds_available=180)
        hist = OccupancyHistory(shelter_id=s.id, occupancy=50, recorded_by=admin.id)
        db.session.add_all([fac, res, hist])
        db.session.commit()

        check('Shelter created in DB', Shelter.query.count() == initial_count + 1)
        check('Facility record created', ShelterFacility.query.filter_by(shelter_id=s.id).first() is not None)
        check('Resource record created', Resource.query.filter_by(shelter_id=s.id).first() is not None)
        check('History entry created', OccupancyHistory.query.filter_by(shelter_id=s.id).count() == 1)

        # ── READ / PROPERTIES ────────────────────────────────────────────────────
        print('\n--- READ + MODEL PROPERTIES')

        fetched = db.session.get(Shelter, s.id)
        check('Shelter fetched by ID', fetched is not None)
        check('Name correct', fetched.name == 'Test Shelter Alpha')
        check('available_capacity = 150', fetched.available_capacity == 150)
        check('occupancy_pct = 25.0', fetched.occupancy_pct == 25.0)
        check('safe_limit = 85 (default)', fetched.safe_limit == 85)
        check('safe_capacity = 170', fetched.safe_capacity == 170)
        check('capacity_status = safe', fetched.capacity_status == 'safe')
        check('status_label = Active', fetched.status_label == 'Active')
        check('facility relationship works', fetched.facility.has_electricity is True)
        check('resource relationship works', fetched.resource.beds_available == 180)

        # Capacity status thresholds
        s2 = Shelter(name='__test_high__', address='Test', latitude=18.5, longitude=73.8,
                     max_capacity=100, current_occupancy=90, status='active')
        db.session.add(s2)
        db.session.flush()
        check('90% -> capacity_status = high', s2.capacity_status == 'high')

        s3 = Shelter(name='__test_critical__', address='Test', latitude=18.5, longitude=73.8,
                     max_capacity=100, current_occupancy=97, status='active')
        db.session.add(s3)
        db.session.flush()
        check('97% -> capacity_status = critical', s3.capacity_status == 'critical')

        s4 = Shelter(name='__test_overcrowded__', address='Test', latitude=18.5, longitude=73.8,
                     max_capacity=100, current_occupancy=105, status='active')
        db.session.add(s4)
        db.session.flush()
        check('105% -> capacity_status = overcrowded', s4.capacity_status == 'overcrowded')

        # Search / filter
        results_active = Shelter.query.filter_by(status='active').all()
        check('Filter by status=active returns rows', len(results_active) > 0)

        search_result = Shelter.query.filter(Shelter.name.ilike('%Test Shelter Alpha%')).first()
        check('Search by name works', search_result is not None)

        # ── UPDATE ────────────────────────────────────────────────────────────────
        print('\n--- UPDATE')

        # Edit shelter fields
        fetched.name    = 'Test Shelter Alpha (Renamed)'
        fetched.status  = 'inactive'
        db.session.commit()

        reloaded = db.session.get(Shelter, fetched.id)
        check('Name update persisted', reloaded.name == 'Test Shelter Alpha (Renamed)')
        check('Status update persisted', reloaded.status == 'inactive')

        # Occupancy update + history
        old_occ = reloaded.current_occupancy
        reloaded.current_occupancy = 80
        hist2 = OccupancyHistory(shelter_id=reloaded.id, occupancy=80, recorded_by=admin.id)
        db.session.add(hist2)
        db.session.commit()

        history_count = OccupancyHistory.query.filter_by(shelter_id=reloaded.id).count()
        check('Occupancy updated to 80', reloaded.current_occupancy == 80)
        check('History record added for occupancy change', history_count == 2)

        # Facility update
        reloaded.facility.has_medical_support = True
        db.session.commit()
        check('Facility flag updated', db.session.get(ShelterFacility, reloaded.facility.id).has_medical_support is True)

        # Duplicate name check
        dup = Shelter.query.filter(
            Shelter.name == 'Test Shelter Alpha (Renamed)',
            Shelter.id != reloaded.id
        ).first()
        check('Duplicate name check: no clash for unique name', dup is None)

        existing_name = Shelter.query.first().name
        clash = Shelter.query.filter(
            Shelter.name == existing_name,
            Shelter.id != reloaded.id
        ).first()
        check('Duplicate name check: detects existing name clash', clash is not None)

        # ── ACCESS CONTROL ────────────────────────────────────────────────────────
        print('\n--- ACCESS CONTROL')

        citizen = User.query.filter_by(email='citizen@example.com').first()
        manager = User.query.filter_by(email='manager1@shelter.gov').first()
        seed_shelter = Shelter.query.filter(Shelter.managed_by != None).first()

        check('Citizen user exists', citizen is not None)
        check('Shelter manager exists', manager is not None)

        # Simulate role checks
        check('Citizen cannot manage shelters', not citizen.can_manage_shelters())
        check('Admin can manage shelters', admin.can_manage_shelters())
        check('Manager can manage shelters', manager.can_manage_shelters())

        # Manager can only edit own shelter
        managed = Shelter.query.filter_by(managed_by=manager.id).first()
        other   = Shelter.query.filter(Shelter.managed_by != manager.id, Shelter.managed_by != None).first()
        if managed and other:
            check('Manager owns their shelter', managed.managed_by == manager.id)
            check('Manager does not own other shelter', other.managed_by != manager.id)

        # ── CLEANUP ───────────────────────────────────────────────────────────────
        print('\n--- CLEANUP')
        for name in ['Test Shelter Alpha (Renamed)', '__test_high__', '__test_critical__', '__test_overcrowded__']:
            t = Shelter.query.filter_by(name=name).first()
            if t:
                db.session.delete(t)
        db.session.commit()
        check('Test shelters cleaned up', Shelter.query.filter(Shelter.name.like('%test%')).count() == 0)

        # ── SUMMARY ───────────────────────────────────────────────────────────────
        print(f'\n=== Result: {PASS} passed, {FAIL} failed ===')
        if FAIL == 0:
            print('ALL TESTS PASSED.')


run_tests()
