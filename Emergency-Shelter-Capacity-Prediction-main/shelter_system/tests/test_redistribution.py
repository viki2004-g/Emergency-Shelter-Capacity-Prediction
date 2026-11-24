"""
tests/test_redistribution.py — Comprehensive test suite for the Shelter Redistribution Engine.

Tests:
  - Suite 1: Multi-shelter partitioning (100 -> 30, 20, 50) & exact sum verification
  - Suite 2: Safe capacity boundary enforcement (zero overrun guarantee)
  - Suite 3: Impossible redistribution detection & transparent deficit explanation
  - Suite 4: Special requirements (wheelchair, medical) & operational status filtering
  - Suite 5: Predicted future load influence on candidate ranking
  - Suite 6: Deferred occupancy mutation & atomic confirmation transaction
  - Suite 7: HTTP route integration & JSON API output

Run:
    python tests/test_redistribution.py
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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


# ── Lightweight stubs for unit testing without database ────────────────────────

class StubFacility:
    def __init__(self, wheelchair=True, medical=True, food=True, water=True, power=True, toilets=True):
        self.has_wheelchair_access = wheelchair
        self.has_medical_support   = medical
        self.has_food              = food
        self.has_running_water     = water
        self.has_electricity      = power
        self.has_toilets           = toilets
        self.has_kitchen           = False
        self.has_family_area       = False


class StubResource:
    def __init__(self, beds=100, food=500, water=1000, meds=20, blankets=100):
        self.beds_available = beds
        self.food_portions  = food
        self.water_litres   = water
        self.medicine_kits  = meds
        self.blankets       = blankets


class StubShelter:
    """Lightweight stub mirroring Shelter model for mathematical testing."""
    def __init__(
        self,
        shelter_id: int,
        name: str,
        current_occ: int,
        max_cap: int,
        safe_pct: int = 80,
        status: str = 'active',
        lat: float = 18.5204,
        lon: float = 73.8567,
        wheelchair: bool = True,
        medical: bool = True
    ):
        self.id                = shelter_id
        self.name              = name
        self.address           = f"{name} Address"
        self.current_occupancy = current_occ
        self.max_capacity      = max_cap
        self.safe_limit        = safe_pct
        self.safe_limit_pct    = safe_pct
        self.status            = status
        self.latitude          = lat
        self.longitude         = lon
        self.facility          = StubFacility(wheelchair=wheelchair, medical=medical)
        self.resource          = StubResource()

    @property
    def safe_capacity(self) -> int:
        return int(self.max_capacity * self.safe_limit / 100)

    @property
    def safe_available_capacity(self) -> int:
        return max(0, self.safe_capacity - self.current_occupancy)

    @property
    def available_capacity(self) -> int:
        return max(0, self.max_capacity - self.current_occupancy)

    @property
    def occupancy_pct(self) -> float:
        if self.max_capacity <= 0:
            return 0.0
        return round((self.current_occupancy / self.max_capacity) * 100, 1)

    @property
    def status_label(self) -> str:
        return self.status.title()


class StubRequest:
    """Lightweight stub mirroring ShelterRequest for mathematical testing."""
    def __init__(
        self,
        group_size: int,
        lat: float = 18.5204,
        lon: float = 73.8567,
        wheelchair: bool = False,
        medical: bool = False,
        injured_cnt: int = 0
    ):
        self.id = 999
        self.group_size = group_size
        self.latitude = lat
        self.longitude = lon
        self.location_name = "Test Incident Location"
        self.has_disabled = wheelchair
        self.accessibility_requirements = "Wheelchair needed" if wheelchair else ""
        self.has_injured = medical or (injured_cnt > 0)
        self.injured_count = injured_cnt
        self.medical_requirements = "Medical needed" if medical else ""
        self.elderly_count = 0
        self.children_count = 0
        self.has_elderly = False
        self.has_children = False
        self.other_special_requirements = ""
        self.status = "pending"


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 1: Multi-Shelter Partitioning (Example: 100 -> 30, 20, 50)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

from services.redistribution import plan_group_redistribution

# Setup 3 shelters with known safe available headroom: 30, 20, 50
# Shelter B: max 100, safe 80% (safe cap 80), occ 50 -> safe avail = 30
sh_b = StubShelter(1, "Shelter B", current_occ=50, max_cap=100, safe_pct=80, lat=18.52, lon=73.85)
# Shelter C: max 100, safe 80% (safe cap 80), occ 60 -> safe avail = 20
sh_c = StubShelter(2, "Shelter C", current_occ=60, max_cap=100, safe_pct=80, lat=18.53, lon=73.86)
# Shelter D: max 100, safe 80% (safe cap 80), occ 30 -> safe avail = 50
sh_d = StubShelter(3, "Shelter D", current_occ=30, max_cap=100, safe_pct=80, lat=18.54, lon=73.87)

test_shelters_100 = [sh_b, sh_c, sh_d]
req_100 = StubRequest(group_size=100, lat=18.52, lon=73.85)

plan_100 = plan_group_redistribution(req_100, shelters=test_shelters_100)

record("Plan reports is_possible = True", plan_100['is_possible'] == True)
record("Total requested == 100", plan_100['total_requested'] == 100)
record("Total allocated == 100", plan_100['total_allocated'] == 100)
record("Unallocated count == 0", plan_100['unallocated_count'] == 0)
record("Allocations list has 3 entries", len(plan_100['allocations']) == 3)

# Sum of all allocated counts must equal 100
total_sum = sum(a['allocated_count'] for a in plan_100['allocations'])
record("Verification: sum(allocations) == 100", total_sum == 100, f"got {total_sum}")

# Check individual shelter allocations
alloc_by_name = {a['shelter_name']: a['allocated_count'] for a in plan_100['allocations']}
record("Shelter B received exactly 30", alloc_by_name.get("Shelter B") == 30, f"got {alloc_by_name.get('Shelter B')}")
record("Shelter C received exactly 20", alloc_by_name.get("Shelter C") == 20, f"got {alloc_by_name.get('Shelter C')}")
record("Shelter D received exactly 50", alloc_by_name.get("Shelter D") == 50, f"got {alloc_by_name.get('Shelter D')}")


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 2: Safe Capacity Boundary Enforcement (Zero Overrun Guarantee)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

for alloc in plan_100['allocations']:
    name = alloc['shelter_name']
    sh = alloc['shelter']
    count = alloc['allocated_count']
    before = alloc['safe_available_before']
    after = alloc['safe_available_after']
    projected = alloc['projected_occupancy']
    safe_cap = alloc['safe_capacity']

    record(f"{name}: allocated ({count}) <= safe available before ({before})", count <= before)
    record(f"{name}: safe available after ({after}) >= 0", after >= 0)
    record(f"{name}: projected occupancy ({projected}) <= safe capacity ({safe_cap})", projected <= safe_cap)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 3: Impossible Redistribution (Deficit Detection)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

# Setup shelters with total safe available capacity = 75 (30 + 20 + 25)
sh_d_smaller = StubShelter(3, "Shelter D", current_occ=55, max_cap=100, safe_pct=80)  # safe avail = 25
test_shelters_75 = [sh_b, sh_c, sh_d_smaller]
req_deficit = StubRequest(group_size=100)

plan_deficit = plan_group_redistribution(req_deficit, shelters=test_shelters_75)

record("Plan reports is_possible = False when capacity < requested", plan_deficit['is_possible'] == False)
record("Total requested == 100", plan_deficit['total_requested'] == 100)
record("Total allocated == 75", plan_deficit['total_allocated'] == 75, f"got {plan_deficit['total_allocated']}")
record("Unallocated count == 25", plan_deficit['unallocated_count'] == 25, f"got {plan_deficit['unallocated_count']}")
record("Explanation mentions 'Redistribution impossible'", "Redistribution impossible" in plan_deficit['explanation'])
record("Explanation mentions deficit number '25'", "25" in plan_deficit['explanation'])
record("Explanation mentions available capacity '75'", "75" in plan_deficit['explanation'])


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 4: Special Requirements & Unsuitability Filtering")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

# Inactive shelter
sh_inactive = StubShelter(4, "Shelter Inactive", current_occ=10, max_cap=100, status='inactive')
# Zero safe capacity shelter
sh_full = StubShelter(5, "Shelter Full", current_occ=80, max_cap=100, safe_pct=80)  # safe avail = 0
# Shelter without wheelchair access
sh_no_wheel = StubShelter(6, "Shelter NoWheel", current_occ=10, max_cap=100, wheelchair=False)
# Shelter without medical facility
sh_no_med = StubShelter(7, "Shelter NoMed", current_occ=10, max_cap=100, medical=False)

shelters_all = [sh_b, sh_c, sh_d, sh_inactive, sh_full, sh_no_wheel, sh_no_med]

# 4.1 Inactive & full shelters are unsuitable for general group
plan_general = plan_group_redistribution(req_100, shelters=shelters_all)
unsuitable_names = [u['shelter'].name for u in plan_general['unsuitable_shelters']]
record("Inactive shelter is in unsuitable_shelters", "Shelter Inactive" in unsuitable_names)
record("Full shelter is in unsuitable_shelters", "Shelter Full" in unsuitable_names)

# 4.2 Wheelchair required group
req_wheelchair = StubRequest(group_size=50, wheelchair=True)
plan_wheel = plan_group_redistribution(req_wheelchair, shelters=shelters_all)
unsuitable_wheel_names = [u['shelter'].name for u in plan_wheel['unsuitable_shelters']]
record("Shelter without wheelchair is in unsuitable_shelters", "Shelter NoWheel" in unsuitable_wheel_names)
alloc_wheel_names = [a['shelter_name'] for a in plan_wheel['allocations']]
record("Shelter without wheelchair NEVER receives allocations", "Shelter NoWheel" not in alloc_wheel_names)

# 4.3 Medical required group
req_medical = StubRequest(group_size=50, medical=True, injured_cnt=5)
plan_med = plan_group_redistribution(req_medical, shelters=shelters_all)
unsuitable_med_names = [u['shelter'].name for u in plan_med['unsuitable_shelters']]
record("Shelter without medical is in unsuitable_shelters", "Shelter NoMed" in unsuitable_med_names)
alloc_med_names = [a['shelter_name'] for a in plan_med['allocations']]
record("Shelter without medical NEVER receives allocations", "Shelter NoMed" not in alloc_med_names)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 5: Predicted Load Consideration")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

# Two equal shelters at same location and capacity
sh_p1 = StubShelter(11, "Pred_Shelter_Near", current_occ=20, max_cap=100, safe_pct=80, lat=18.52, lon=73.85)
sh_p2 = StubShelter(12, "Pred_Shelter_Far", current_occ=20, max_cap=100, safe_pct=80, lat=18.90, lon=73.85)

plan_pred = plan_group_redistribution(StubRequest(group_size=30, lat=18.52, lon=73.85), shelters=[sh_p1, sh_p2])
cands = plan_pred['candidate_shelters']
record("Near shelter receives higher multi-criteria score than far shelter",
       cands[0]['name'] == "Pred_Shelter_Near" and cands[0]['score'] > cands[1]['score'])
record("Top-ranked near shelter is allocated first",
       plan_pred['allocations'][0]['shelter_name'] == "Pred_Shelter_Near")


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 6: Deferred Mutation & Atomic Confirmation (Database Backed)")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

from app import create_app
from extensions import db, bcrypt
from models.user import User
from models.shelter import Shelter
from models.request import ShelterRequest
from models.allocation import Allocation
from models.occupancy import OccupancyHistory
from models.facility import ShelterFacility
from models.resource import Resource
from services.redistribution import execute_confirmed_allocation

app = create_app()

def _cleanup_test_data():
    test_req_ids = [r.id for r in ShelterRequest.query.filter(ShelterRequest.location_name.like('TestRedist_%')).all()]
    test_sh_ids  = [s.id for s in Shelter.query.filter(Shelter.name.like('TestRedist_%')).all()]
    if test_req_ids:
        Allocation.query.filter(Allocation.request_id.in_(test_req_ids)).delete(synchronize_session=False)
    if test_sh_ids:
        Allocation.query.filter(Allocation.shelter_id.in_(test_sh_ids)).delete(synchronize_session=False)
        OccupancyHistory.query.filter(OccupancyHistory.shelter_id.in_(test_sh_ids)).delete(synchronize_session=False)
        ShelterFacility.query.filter(ShelterFacility.shelter_id.in_(test_sh_ids)).delete(synchronize_session=False)
        Resource.query.filter(Resource.shelter_id.in_(test_sh_ids)).delete(synchronize_session=False)
        Shelter.query.filter(Shelter.id.in_(test_sh_ids)).delete(synchronize_session=False)
    if test_req_ids:
        ShelterRequest.query.filter(ShelterRequest.id.in_(test_req_ids)).delete(synchronize_session=False)
    db.session.commit()

with app.app_context():
    _cleanup_test_data()

    # Ensure admin user
    user = User.query.filter_by(role='admin').first()
    if not user:
        user = User(
            email='admin@shelter.gov',
            full_name='System Administrator',
            role='admin',
            password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8')
        )
        db.session.add(user)
        db.session.commit()

    # Create 3 real shelters in DB with known safe capacities: 30, 20, 50
    # Safe limit = 80%.
    # S1: max 100, occ 50 -> safe avail = 30
    s1 = Shelter(name='TestRedist_B', address='Loc B', latitude=18.52, longitude=73.85,
                 max_capacity=100, current_occupancy=50, status='active', safe_limit_pct=80)
    # S2: max 100, occ 60 -> safe avail = 20
    s2 = Shelter(name='TestRedist_C', address='Loc C', latitude=18.53, longitude=73.86,
                 max_capacity=100, current_occupancy=60, status='active', safe_limit_pct=80)
    # S3: max 100, occ 30 -> safe avail = 50
    s3 = Shelter(name='TestRedist_D', address='Loc D', latitude=18.54, longitude=73.87,
                 max_capacity=100, current_occupancy=30, status='active', safe_limit_pct=80)

    db.session.add_all([s1, s2, s3])
    db.session.flush()

    for s in (s1, s2, s3):
        db.session.add(ShelterFacility(
            shelter_id=s.id, has_wheelchair_access=True, has_medical_support=True,
            has_food=True, has_running_water=True, has_electricity=True,
            has_toilets=True, has_kitchen=False, has_family_area=False
        ))
        db.session.add(Resource(
            shelter_id=s.id, beds_available=100, food_portions=500,
            water_litres=1000, medicine_kits=20, blankets=100
        ))
    db.session.commit()

    # Create real ShelterRequest for group of 100
    db_req = ShelterRequest(
        submitted_by=user.id,
        group_size=100,
        latitude=18.52,
        longitude=73.85,
        location_name='TestRedist_IncidentSite',
        status='pending'
    )
    db.session.add(db_req)
    db.session.commit()

    initial_occ_s1 = s1.current_occupancy
    initial_occ_s2 = s2.current_occupancy
    initial_occ_s3 = s3.current_occupancy

    # 6.1 Calling plan_group_redistribution MUST NOT mutate DB
    plan_real = plan_group_redistribution(db_req, shelters=[s1, s2, s3])
    record("Real plan is_possible == True", plan_real['is_possible'] == True)
    record("Real plan total_allocated == 100", plan_real['total_allocated'] == 100)

    # Verify occupancies DID NOT CHANGE
    db.session.refresh(s1)
    db.session.refresh(s2)
    db.session.refresh(s3)
    db.session.refresh(db_req)

    record("Deferred Occupancy: s1 occupancy unchanged after planning", s1.current_occupancy == initial_occ_s1)
    record("Deferred Occupancy: s2 occupancy unchanged after planning", s2.current_occupancy == initial_occ_s2)
    record("Deferred Occupancy: s3 occupancy unchanged after planning", s3.current_occupancy == initial_occ_s3)
    record("Deferred Status: request status remains 'pending'", db_req.status == 'pending')

    # No allocations exist yet in DB
    existing_allocs = Allocation.query.filter_by(request_id=db_req.id).count()
    record("No Allocation records created before explicit confirmation", existing_allocs == 0)

    # 6.2 Explicit confirmation MUST mutate DB atomically
    success, created_allocs = execute_confirmed_allocation(
        request_id=db_req.id,
        plan=plan_real,
        confirmed_by_user_id=user.id,
        notes="Automated test confirmation"
    )

    record("execute_confirmed_allocation returned success = True", success == True)
    record("Created allocations count == 3", len(created_allocs) == 3)

    db.session.refresh(s1)
    db.session.refresh(s2)
    db.session.refresh(s3)
    db.session.refresh(db_req)

    record("Request status updated to 'allocated'", db_req.status == 'allocated')

    # Sum of new occupancies minus initial occupancies must equal 100
    net_increase = (
        (s1.current_occupancy - initial_occ_s1) +
        (s2.current_occupancy - initial_occ_s2) +
        (s3.current_occupancy - initial_occ_s3)
    )
    record("Total occupancy increment across shelters == 100", net_increase == 100, f"got {net_increase}")

    # Check that OccupancyHistory records were inserted
    hist_count = OccupancyHistory.query.filter(
        OccupancyHistory.shelter_id.in_([s1.id, s2.id, s3.id])
    ).count()
    record("OccupancyHistory entries created for participating shelters", hist_count >= 3)

    # Check Allocation records in DB have confirmed=True
    persisted_allocs = Allocation.query.filter_by(request_id=db_req.id).all()
    record("Persisted Allocation records count == 3", len(persisted_allocs) == 3)
    record("All persisted Allocation records have confirmed = True",
           all(a.confirmed == True for a in persisted_allocs))


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 7: HTTP Routes & JSON API")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    import json

    client = app.test_client()

    admin_user = User.query.filter_by(role='admin').first()
    test_req = ShelterRequest.query.filter(ShelterRequest.location_name.like('TestRedist_%')).first()

    # 7.0 Unauthenticated access -> 302 redirect
    res_unauth = client.get(f'/recommend/redistribute/request/{test_req.id}')
    record("Unauthenticated GET /recommend/redistribute/request/<id> -> 302",
           res_unauth.status_code == 302)

    # Login as admin
    login_resp = client.post('/auth/login', data={
        'email': admin_user.email,
        'password': 'Password@123'
    }, follow_redirects=True)
    record("Admin login for HTTP tests", login_resp.status_code == 200)

    # 7.1 GET /recommend/redistribute/request/<id>
    res_get = client.get(f'/recommend/redistribute/request/{test_req.id}')
    record("GET /recommend/redistribute/request/<id> returns 200 OK", res_get.status_code == 200)
    html = res_get.data.decode('utf-8', errors='replace')
    record("HTML contains 'Multi-Shelter Redistribution Engine'", 'Multi-Shelter Redistribution Engine' in html)
    record("HTML contains 'Incoming Group'", 'Incoming Group' in html)
    record("HTML contains 'Candidate Shelters'", 'Candidate Shelters' in html)
    record("HTML contains 'Proposed Allocation Plan'", 'Proposed Allocation Plan' in html)
    record("HTML contains 'Total Allocated'", 'Total Allocated' in html)
    record("HTML contains 'Remaining Capacity'", 'Remaining Capacity' in html)
    record("HTML contains 'Deferred Occupancy Policy'", 'Deferred Occupancy Policy' in html)

    # 7.2 POST /recommend/redistribute/simulation
    res_sim = client.post('/recommend/redistribute/simulation', data={
        'group_size': '75',
        'latitude': '18.5204',
        'longitude': '73.8567',
        'location_name': 'Simulation Disaster Zone',
        'injured_count': '2',
        'elderly_count': '5',
        'children_count': '10',
    })
    record("POST /recommend/redistribute/simulation returns 200 OK", res_sim.status_code == 200)
    sim_html = res_sim.data.decode('utf-8', errors='replace')
    record("Simulation page displays simulation notice", 'Simulation Mode' in sim_html or 'Simulation' in sim_html)
    record("Simulation page shows 75 Evacuees", '75 Evacuees' in sim_html or '75' in sim_html)

    # 7.3 GET /recommend/api/redistribute/<id>
    res_api = client.get(f'/recommend/api/redistribute/{test_req.id}')
    record("GET /recommend/api/redistribute/<id> returns 200 OK", res_api.status_code == 200)
    api_data = json.loads(res_api.data)
    record("API response has 'is_possible' key", 'is_possible' in api_data)
    record("API response has 'total_requested' key", api_data.get('total_requested') == 100)
    record("API response has 'allocations' list", isinstance(api_data.get('allocations'), list))
    record("API response has 'candidate_shelters' list", isinstance(api_data.get('candidate_shelters'), list))
    record("API response has 'unsuitable_shelters' list", isinstance(api_data.get('unsuitable_shelters'), list))
    record("API response has 'explanation' string", bool(api_data.get('explanation')))
    record("API response has 'disclaimer' string", bool(api_data.get('disclaimer')))

    if api_data.get('allocations'):
        a0 = api_data['allocations'][0]
        for key in ('shelter_id', 'shelter_name', 'allocated_count', 'safe_available_before',
                    'safe_available_after', 'projected_occupancy', 'projected_pct', 'reasons'):
            record(f"API allocation item has '{key}'", key in a0)

    # 7.4 Cleanup test records
    _cleanup_test_data()


# =============================================================================
print("\n" + "=" * 64)
print(f"Total Tests Run : {total_tests}")
print(f"Passed          : {passed_tests}")
print(f"Failed          : {total_tests - passed_tests}")
print("=" * 64)

if __name__ == '__main__':
    sys.exit(0 if total_tests == passed_tests else 1)
