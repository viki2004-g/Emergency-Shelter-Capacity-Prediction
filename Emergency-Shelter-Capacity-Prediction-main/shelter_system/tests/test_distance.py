"""
tests/test_distance.py -- Comprehensive test suite for the Haversine distance service.

Verifies correctness using real-world city coordinate pairs whose distances
are independently published and can be cross-checked with mapping tools.

Test Suites:
  1. Known City-Pair Distances  -- validates against accepted reference values
  2. Edge Cases                 -- same point, antipodal, poles, equator crossing
  3. Symmetry & Non-negativity  -- d(A,B) == d(B,A), always >= 0
  4. Invalid Input Handling     -- None, strings, NaN return sentinel 9999.0
  5. distance_band() Labels     -- correct band for each distance range
  6. Recommendation Integration -- distance flows correctly into engine output

Run:
    python tests/test_distance.py
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.distance import haversine_distance, distance_band, BAND_LABELS

total_tests  = 0
passed_tests = 0


def record(label: str, passed: bool, detail: str = ""):
    global total_tests, passed_tests
    total_tests += 1
    if passed:
        passed_tests += 1
        print(f"  [PASS] {label}")
    else:
        print(f"  [FAIL] {label}  ->  {detail}")


def approx(got: float, expected: float, tolerance_km: float = 5.0) -> bool:
    """True if |got - expected| <= tolerance_km."""
    return abs(got - expected) <= tolerance_km


# -----------------------------------------------------------------------------

def run_distance_tests():
    global total_tests, passed_tests
    print("\n" + "=" * 64)
    print("Suite 1: Known City-Pair Distances")
    print("=" * 64)
    print("  (tolerance: +/-5 km -- accounts for spherical Earth approximation)")
    # -----------------------------------------------------------------------------
    
    # Each entry: (label, lat1, lon1, lat2, lon2, expected_km, tolerance_km)
    KNOWN_PAIRS = [
        # -- India -- relevant to the project's default coordinates ------------
        (
            "Pune -> Mumbai  (major city pair, ~116 km)",
            18.5204, 73.8567,   # Pune, Maharashtra
            19.0760, 72.8777,   # Mumbai, Maharashtra
            116.0, 5.0,
        ),
        (
            "Pune -> Nashik  (~164 km great-circle)",
            18.5204, 73.8567,
            19.9975, 73.7898,
            164.0, 5.0,
        ),
        (
            "Pune -> Aurangabad  (~217 km great-circle)",
            18.5204, 73.8567,
            19.8762, 75.3433,
            217.0, 5.0,
        ),
        (
            "Mumbai -> Delhi  (~1148 km national air route)",
            19.0760, 72.8777,
            28.6139, 77.2090,
            1148.0, 10.0,
        ),
        (
            "Same city -- Shivajinagar -> Kothrud Pune  (~3 km)",
            18.5204, 73.8567,
            18.5074, 73.8077,
            4.5, 2.0,
        ),
    
        # -- International reference pairs -------------------------------------
        (
            "London -> Paris  (~341 km, widely published reference)",
            51.5074, -0.1278,
            48.8566,  2.3522,
            341.0, 5.0,
        ),
        (
            "New York -> Los Angeles  (~3940 km great-circle)",
            40.7128, -74.0060,
            34.0522, -118.2437,
            3940.0, 20.0,
        ),
        (
            "Sydney -> Auckland  (~2156 km across Tasman Sea)",
            -33.8688, 151.2093,
            -36.8485, 174.7633,
            2156.0, 15.0,
        ),
        (
            "Nairobi -> Johannesburg  (~2925 km great-circle)",
            -1.2921,  36.8219,
            -26.2041,  28.0473,
            2925.0, 15.0,
        ),
    ]
    
    for label, lat1, lon1, lat2, lon2, expected, tol in KNOWN_PAIRS:
        got = haversine_distance(lat1, lon1, lat2, lon2)
        record(
            label,
            approx(got, expected, tol),
            f"got {got} km, expected ~{expected} km (+/-{tol} km)"
        )
    
    # -----------------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("Suite 2: Edge Cases")
    print("=" * 64)
    # -----------------------------------------------------------------------------
    
    # 2.1 Identical point -- distance must be exactly 0.0
    d_same = haversine_distance(18.5204, 73.8567, 18.5204, 73.8567)
    record("Identical coordinates return 0.0 km", d_same == 0.0, f"got {d_same}")
    
    # 2.2 Antipodal points -- maximum possible great-circle distance ~ pi x R ~ 20015 km
    d_antipodal = haversine_distance(0.0, 0.0, 0.0, 180.0)
    record(
        "Antipodal points (0degN 0degE -> 0degN 180degE) ~ 20015 km",
        approx(d_antipodal, 20015.0, 20.0),
        f"got {d_antipodal} km"
    )
    
    # 2.3 North Pole -> South Pole ~ 20015 km
    d_poles = haversine_distance(90.0, 0.0, -90.0, 0.0)
    record(
        "North Pole -> South Pole ~ 20015 km",
        approx(d_poles, 20015.0, 20.0),
        f"got {d_poles} km"
    )
    
    # 2.4 Pure latitude change -- moving 1deg north ~ 111 km
    d_1deg_lat = haversine_distance(0.0, 0.0, 1.0, 0.0)
    record(
        "1deg latitude difference on equator ~ 111 km",
        approx(d_1deg_lat, 111.195, 1.0),
        f"got {d_1deg_lat} km"
    )
    
    # 2.5 Pure longitude change on equator -- 1deg ~ 111 km
    d_1deg_lon = haversine_distance(0.0, 0.0, 0.0, 1.0)
    record(
        "1deg longitude difference on equator ~ 111 km",
        approx(d_1deg_lon, 111.195, 1.0),
        f"got {d_1deg_lon} km"
    )
    
    # 2.6 Pure longitude change at 60deg latitude -- 1deg ~ 55.6 km (cos 60deg = 0.5)
    d_60lat = haversine_distance(60.0, 0.0, 60.0, 1.0)
    record(
        "1deg longitude at 60degN latitude ~ 55.6 km  (longitude degrees shrink poleward)",
        approx(d_60lat, 55.6, 1.5),
        f"got {d_60lat} km"
    )
    
    # 2.7 Very short distance -- shelter next door (~10 m apart)
    d_tiny = haversine_distance(18.5204, 73.8567, 18.52041, 73.85671)
    record(
        "Coordinates ~10 m apart return near-zero distance",
        d_tiny < 0.05,
        f"got {d_tiny} km"
    )
    
    # -----------------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("Suite 3: Symmetry & Non-negativity")
    print("=" * 64)
    # -----------------------------------------------------------------------------
    
    # 3.1 Symmetry: d(A, B) must equal d(B, A)
    SYMMETRY_PAIRS = [
        (18.5204, 73.8567, 19.0760, 72.8777),  # Pune -> Mumbai
        (51.5074, -0.1278, 48.8566,  2.3522),  # London -> Paris
        (90.0, 0.0, -90.0, 0.0),              # poles
    ]
    for lat1, lon1, lat2, lon2 in SYMMETRY_PAIRS:
        ab = haversine_distance(lat1, lon1, lat2, lon2)
        ba = haversine_distance(lat2, lon2, lat1, lon1)
        record(
            f"Symmetry d({lat1:.1f},{lon1:.1f}) <-> d({lat2:.1f},{lon2:.1f}): {ab} == {ba}",
            ab == ba,
            f"A->B={ab} B->A={ba}"
        )
    
    # 3.2 Non-negativity: distance must always be >= 0
    for lat1, lon1, lat2, lon2 in SYMMETRY_PAIRS:
        d = haversine_distance(lat1, lon1, lat2, lon2)
        record(f"Non-negative: d({lat1},{lon1},{lat2},{lon2}) >= 0", d >= 0.0, f"got {d}")
    
    # -----------------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("Suite 4: Invalid Input Handling")
    print("=" * 64)
    # -----------------------------------------------------------------------------
    
    # 4.1-4.4 Non-numeric inputs -> sentinel 9999.0
    bad_inputs = [
        ("None values",        None,    None,    None,    None),
        ("String coordinates", "north", "east",  "south", "west"),
        ("Empty strings",      "",      "",      "",      ""),
        ("Mixed valid/invalid",18.52,   73.85,   "bad",   None),
    ]
    for label, la1, lo1, la2, lo2 in bad_inputs:
        d = haversine_distance(la1, lo1, la2, lo2)
        record(f"Invalid input '{label}' -> 9999.0 sentinel", d == 9999.0, f"got {d}")
    
    # 4.5 Return type is always float
    d_type = haversine_distance(18.5204, 73.8567, 19.0760, 72.8777)
    record("Return type is float", isinstance(d_type, float), f"got {type(d_type)}")
    
    # 4.6 Result is rounded to 2 decimal places
    import math as _math
    d_precision = haversine_distance(18.5204, 73.8567, 19.0760, 72.8777)
    record(
        "Result rounded to 2 decimal places",
        d_precision == round(d_precision, 2),
        f"got {d_precision}"
    )
    
    # -----------------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("Suite 5: distance_band() Proximity Labels")
    print("=" * 64)
    # -----------------------------------------------------------------------------
    
    BAND_CASES = [
        (0.0,   'immediate', "0 km -> immediate"),
        (1.5,   'immediate', "1.5 km -> immediate"),
        (1.99,  'immediate', "1.99 km -> immediate"),
        (2.0,   'close',     "2.0 km -> close"),
        (5.0,   'close',     "5.0 km -> close"),
        (9.99,  'close',     "9.99 km -> close"),
        (10.0,  'moderate',  "10.0 km -> moderate"),
        (20.0,  'moderate',  "20.0 km -> moderate"),
        (24.99, 'moderate',  "24.99 km -> moderate"),
        (25.0,  'far',       "25.0 km -> far"),
        (40.0,  'far',       "40.0 km -> far"),
        (49.99, 'far',       "49.99 km -> far"),
        (50.0,  'very_far',  "50.0 km -> very_far"),
        (200.0, 'very_far',  "200.0 km -> very_far"),
    ]
    for dist, expected_band, label in BAND_CASES:
        got_band = distance_band(dist)
        record(
            f"distance_band({dist} km) == '{expected_band}' ({label})",
            got_band == expected_band,
            f"got '{got_band}'"
        )
    
    # 5.x All bands have a BAND_LABELS entry
    for band in ('immediate', 'close', 'moderate', 'far', 'very_far'):
        record(
            f"BAND_LABELS['{band}'] is a non-empty string",
            bool(BAND_LABELS.get(band, '')),
            f"got '{BAND_LABELS.get(band)}'"
        )
    
    # -----------------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("Suite 6: Integration with Recommendation Engine")
    print("=" * 64)
    # -----------------------------------------------------------------------------
    # Import app context for DB-backed recommendation tests
    from app import create_app
    from extensions import db
    from models.user import User
    from models.shelter import Shelter
    from models.facility import ShelterFacility
    from models.resource import Resource
    from models.request import ShelterRequest
    from services.recommendation import evaluate_shelter_candidates
    
    app = create_app()
    
    with app.app_context():
    
        # Clean up any leftover test shelters
        Shelter.query.filter(Shelter.name.like('TestDist_%')).delete(synchronize_session=False)
        db.session.commit()
    
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            admin = User(email='dist_admin@shelter.test', full_name='Distance Test Admin', role='admin')
            admin.set_password('Password@123')
            db.session.add(admin)
            db.session.commit()
    
        # Create two shelters at known distances from the test incident point
        # Incident point: Pune city centre (18.5204, 73.8567)
        #   Shelter Near: 1 km away  -> (18.5294, 73.8567)  approx +0.009deg lat ~ 1 km
        #   Shelter Far:  50 km away -> (19.0204, 73.8567)  approx +0.5deg lat ~ 55 km
    
        # Near shelter -- active, enough capacity, full facilities
        sh_near = Shelter(
            name='TestDist_Near_Shelter',
            address='Near Test Point',
            latitude=18.5294, longitude=73.8567,
            max_capacity=200, current_occupancy=50,
            status='active', safe_limit_pct=85
        )
        db.session.add(sh_near)
        db.session.flush()
        db.session.add(ShelterFacility(
            shelter_id=sh_near.id,
            has_wheelchair_access=True, has_medical_support=True,
            has_food=True, has_running_water=True, has_electricity=True,
            has_toilets=True, has_kitchen=True, has_family_area=True
        ))
        db.session.add(Resource(
            shelter_id=sh_near.id,
            beds_available=100, food_portions=500,
            water_litres=1000, medicine_kits=20, blankets=100
        ))
    
        # Far shelter -- same specs, but far away
        sh_far = Shelter(
            name='TestDist_Far_Shelter',
            address='Far Test Point',
            latitude=19.0204, longitude=73.8567,
            max_capacity=200, current_occupancy=50,
            status='active', safe_limit_pct=85
        )
        db.session.add(sh_far)
        db.session.flush()
        db.session.add(ShelterFacility(
            shelter_id=sh_far.id,
            has_wheelchair_access=True, has_medical_support=True,
            has_food=True, has_running_water=True, has_electricity=True,
            has_toilets=True, has_kitchen=True, has_family_area=True
        ))
        db.session.add(Resource(
            shelter_id=sh_far.id,
            beds_available=100, food_portions=500,
            water_litres=1000, medicine_kits=20, blankets=100
        ))
        db.session.commit()
    
        test_shelters = [sh_near, sh_far]
    
        # Verify calculated distances are in the expected bands
        d_near = haversine_distance(18.5204, 73.8567, float(sh_near.latitude), float(sh_near.longitude))
        d_far  = haversine_distance(18.5204, 73.8567, float(sh_far.latitude),  float(sh_far.longitude))
    
        record(
            f"Near shelter distance < 5 km (got {d_near} km)",
            d_near < 5.0,
            f"expected < 5.0, got {d_near}"
        )
        record(
            f"Far shelter distance 45-65 km (got {d_far} km)",
            45.0 <= d_far <= 65.0,
            f"expected 45-65 km, got {d_far}"
        )
        record(
            "Near shelter distance < Far shelter distance",
            d_near < d_far,
            f"near={d_near}, far={d_far}"
        )
    
        # Run recommendation engine -- distance-heavy weights should rank Near #1
        req = ShelterRequest(
            submitted_by=admin.id,
            group_size=10,
            latitude=18.5204, longitude=73.8567,
            location_name='TestDist_IncidentPoint'
        )
        # With 90% weight on distance, the near shelter must rank #1
        result = evaluate_shelter_candidates(
            req,
            shelters=test_shelters,
            custom_weights={'distance': 0.9, 'capacity': 0.05, 'facilities': 0.025, 'resources': 0.025}
        )
        record(
            "Recommendation engine returns 2 eligible shelters",
            result['total_eligible'] == 2,
            f"got {result['total_eligible']}"
        )
        rec = result['recommended_shelter']
        record("Recommended shelter exists", rec is not None)
        record(
            "Near shelter ranked #1 (distance-heavy weights)",
            rec['shelter'].id == sh_near.id if rec else False,
            f"got id={rec['shelter'].id if rec else None}, near id={sh_near.id}"
        )
        record(
            "distance_km is present in candidate dict",
            'distance_km' in rec if rec else False
        )
        record(
            "Positive reasons contain distance label from BAND_LABELS",
            any('km' in r.lower() for r in rec['positive_reasons']) if rec else False,
            f"reasons: {rec['positive_reasons'] if rec else []}"
        )
    
        # Verify distance_km values in eligible_shelters match haversine directly
        for cand in result['eligible_shelters']:
            expected_d = haversine_distance(
                18.5204, 73.8567,
                float(cand['shelter'].latitude), float(cand['shelter'].longitude)
            )
            record(
                f"Engine distance_km for '{cand['shelter'].name}' matches direct haversine call ({expected_d} km)",
                cand['distance_km'] == expected_d,
                f"engine={cand['distance_km']}, direct={expected_d}"
            )
    
        # Clean up
        Shelter.query.filter(Shelter.name.like('TestDist_%')).delete(synchronize_session=False)
        db.session.commit()
    
    # -----------------------------------------------------------------------------
    print("\n" + "=" * 64)
    print(f"Total Tests Run : {total_tests}")
    print(f"Passed          : {passed_tests}")
    print(f"Failed          : {total_tests - passed_tests}")
    print("=" * 64)
    
if __name__ == '__main__':
    run_distance_tests()
    sys.exit(0 if total_tests == passed_tests else 1)
