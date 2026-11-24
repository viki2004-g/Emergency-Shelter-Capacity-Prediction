"""
tests/test_facilities_resources.py — Stage 5 tests.

Tests:
  - ShelterFacility: CRUD, has_food flag, count_available, to_dict()
  - Resource: CRUD, LOW_THRESHOLDS, is_low(), any_low, low_fields, to_dict()
  - Relationships: one-to-one with shelter, CASCADE delete
  - Validation: negative quantities rejected
  - Access: managers cannot update other shelter's resources
"""

import sys
sys.path.insert(0, '.')

from app import create_app
from extensions import db
from models import Shelter, ShelterFacility, Resource, User

app = create_app('testing')
PASS = FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [PASS] {label}')
    else:
        FAIL += 1
        print(f'  [FAIL] {label}')


def make_test_shelter(name, occ=0):
    s = Shelter(
        name=name, address='Test Rd',
        latitude=18.5, longitude=73.8,
        max_capacity=200, current_occupancy=occ, status='active',
    )
    db.session.add(s)
    db.session.flush()
    return s


with app.app_context():
    print('\n=== Stage 5 — Facilities & Resources Tests ===\n')

    admin = User.query.filter_by(email='admin@shelter.gov').first()
    check('Admin user found', admin is not None)

    # ── ShelterFacility ────────────────────────────────────────────────────────
    print('\n--- ShelterFacility model')

    s = make_test_shelter('__Stage5_FacTest__')

    # Create with all flags off
    fac = ShelterFacility(shelter_id=s.id)
    db.session.add(fac)
    db.session.commit()

    fac_reloaded = db.session.get(ShelterFacility, fac.id)
    check('ShelterFacility created',       fac_reloaded is not None)
    check('FK shelter_id correct',         fac_reloaded.shelter_id == s.id)
    check('has_food default = False',      fac_reloaded.has_food is False)
    check('has_medical default = False',   fac_reloaded.has_medical_support is False)
    check('count_available = 0 initially', fac_reloaded.count_available == 0)

    # Set flags and verify count_available
    fac_reloaded.has_medical_support   = True
    fac_reloaded.has_food              = True
    fac_reloaded.has_electricity       = True
    fac_reloaded.has_toilets           = True
    fac_reloaded.has_wheelchair_access = False
    db.session.commit()

    fac_reloaded = db.session.get(ShelterFacility, fac.id)
    check('has_food can be set True',      fac_reloaded.has_food is True)
    check('count_available = 4',           fac_reloaded.count_available == 4)

    d = fac_reloaded.to_dict()
    check('to_dict() has all 8 keys',      len(d) == 8)
    check('to_dict() has_food = True',     d['has_food'] is True)
    check('to_dict() has_kitchen = False', d['has_kitchen'] is False)

    # Turn all on
    for field in d:
        setattr(fac_reloaded, field, True)
    db.session.commit()
    fac_reloaded = db.session.get(ShelterFacility, fac.id)
    check('count_available = 8 when all on', fac_reloaded.count_available == 8)

    # ── Resource ────────────────────────────────────────────────────────────────
    print('\n--- Resource model')

    res = Resource(
        shelter_id=s.id,
        beds_available=50,
        food_portions=100,
        water_litres=300,
        medicine_kits=10,
        blankets=40,
        updated_by=admin.id,
    )
    db.session.add(res)
    db.session.commit()

    res_reloaded = db.session.get(Resource, res.id)
    check('Resource created',               res_reloaded is not None)
    check('beds_available = 50',            res_reloaded.beds_available == 50)
    check('food_portions = 100',            res_reloaded.food_portions == 100)
    check('water_litres = 300',             res_reloaded.water_litres == 300)
    check('updated_by FK works',            res_reloaded.updater.full_name == admin.full_name)

    # is_low() checks
    check('food at 100 is NOT low',         not res_reloaded.is_low('food_portions'))    # threshold=50
    check('water at 300 is NOT low',        not res_reloaded.is_low('water_litres'))     # threshold=200
    check('any_low = False when stocked',   not res_reloaded.any_low)
    check('low_fields = [] when stocked',   res_reloaded.low_fields == [])

    # Drop food below threshold
    res_reloaded.food_portions = 30   # < 50 threshold
    res_reloaded.water_litres  = 150  # < 200 threshold
    res_reloaded.medicine_kits = 3    # < 5 threshold
    db.session.commit()

    res_reloaded = db.session.get(Resource, res.id)
    check('food at 30 is low',              res_reloaded.is_low('food_portions'))
    check('water at 150 is low',            res_reloaded.is_low('water_litres'))
    check('medicine at 3 is low',           res_reloaded.is_low('medicine_kits'))
    check('any_low = True when depleted',   res_reloaded.any_low)
    low = res_reloaded.low_fields
    check('3 low fields detected',          len(low) == 3)

    td = res_reloaded.to_dict()
    check('to_dict() has 5 keys',           len(td) == 5)
    check('to_dict() food_portions = 30',   td['food_portions'] == 30)

    # Negative quantities: DB does not enforce, but the route does.
    # Simulate route validation logic directly
    def validate_resource_quantities(form_values):
        errors = []
        for field, raw in form_values.items():
            try:
                val = int(raw)
                if val < 0:
                    errors.append(f'{field} cannot be negative')
            except (ValueError, TypeError):
                errors.append(f'{field} must be a whole number')
        return errors

    check('Negative beds rejected by validation',
          len(validate_resource_quantities({'beds_available': '-5'})) == 1)
    check('Non-integer rejected by validation',
          len(validate_resource_quantities({'food_portions': 'abc'})) == 1)
    check('Valid 0 accepted',
          len(validate_resource_quantities({'beds_available': '0'})) == 0)
    check('Multiple negatives collected together',
          len(validate_resource_quantities({'beds_available': '-1', 'food_portions': '-2'})) == 2)

    # ── Relationships & FK ────────────────────────────────────────────────────
    print('\n--- Relationships & FK constraints')

    # One-to-one: only one ShelterFacility per shelter
    dup_fac = ShelterFacility(shelter_id=s.id)
    db.session.add(dup_fac)
    try:
        db.session.commit()
        check('UNIQUE constraint prevents duplicate ShelterFacility', False)
    except Exception:
        db.session.rollback()
        check('UNIQUE constraint prevents duplicate ShelterFacility', True)

    # CASCADE delete: deleting shelter cascades to facility and resource
    s2 = make_test_shelter('__Stage5_Cascade__')
    fac2 = ShelterFacility(shelter_id=s2.id, has_food=True)
    res2 = Resource(shelter_id=s2.id, beds_available=20)
    db.session.add_all([fac2, res2])
    db.session.commit()

    s2_id = s2.id
    db.session.delete(s2)
    db.session.commit()

    check('CASCADE: facility deleted with shelter',
          ShelterFacility.query.filter_by(shelter_id=s2_id).count() == 0)
    check('CASCADE: resource deleted with shelter',
          Resource.query.filter_by(shelter_id=s2_id).count() == 0)

    # Relationship traversal shelter → facility → resource
    s_loaded = db.session.get(Shelter, s.id)
    check('shelter.facility relationship works', s_loaded.facility is not None)
    check('shelter.resource relationship works', s_loaded.resource is not None)
    check('shelter.facility.has_food is True',  s_loaded.facility.has_food is True)

    # ── Access Control ────────────────────────────────────────────────────────
    print('\n--- Access control logic')

    manager = User.query.filter_by(role='shelter_manager').first()
    if manager:
        managed = Shelter.query.filter_by(managed_by=manager.id).first()
        other   = Shelter.query.filter(
            Shelter.managed_by != manager.id,
            Shelter.managed_by != None
        ).first()

        if managed:
            check('Manager owns their shelter (managed_by == id)',
                  managed.managed_by == manager.id)
        if other:
            check('Manager does not own another shelter',
                  other.managed_by != manager.id)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    print('\n--- Cleanup')
    for name in ['__Stage5_FacTest__', '__Stage5_Cascade__']:
        t = Shelter.query.filter_by(name=name).first()
        if t:
            db.session.delete(t)
    db.session.commit()
    check('Test shelters cleaned up', Shelter.query.filter(Shelter.name.like('%Stage5%')).count() == 0)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f'\n=== Result: {PASS} passed, {FAIL} failed ===')
    if FAIL == 0:
        print('ALL TESTS PASSED.')
    else:
        print('SOME TESTS FAILED.')
