"""
tests/test_prediction.py — Comprehensive test suite for the MVP occupancy prediction engine.

Tests the core formula, risk classification, edge cases, forecast series shape,
batch predictions, and HTTP API endpoints.

All tests use lightweight mock/stub objects where possible to avoid DB dependency,
and use the full Flask app context where DB access is required.

Run:
    python tests/test_prediction.py
"""

import sys
import os
from datetime import datetime, timedelta

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


# ── Lightweight stubs (no DB) ─────────────────────────────────────────────────

class FakeShelter:
    """Minimal stub that mirrors the Shelter model interface used by prediction.py."""
    def __init__(self, shelter_id, current_occupancy, max_capacity, safe_limit=85):
        self.id                = shelter_id
        self.current_occupancy = current_occupancy
        self.max_capacity      = max_capacity
        self.safe_limit        = safe_limit   # percentage (e.g. 85 means 85%)

    @property
    def safe_capacity(self):
        return int(self.max_capacity * self.safe_limit / 100)

    @property
    def occupancy_pct(self):
        if self.max_capacity == 0:
            return 0.0
        return round(self.current_occupancy / self.max_capacity * 100, 1)


class FakeHistory:
    """Minimal stub that mirrors OccupancyHistory records used by _calculate_rate."""
    def __init__(self, occupancy: int, hours_ago: float):
        self.occupancy   = occupancy
        self.recorded_at = datetime.utcnow() - timedelta(hours=hours_ago)
        self.shelter     = None
        self.recorder    = None


# ── Import service functions directly (no Flask app needed for pure logic) ────

from services.prediction import (
    _calculate_rate,
    _classify_risk,
    generate_forecast_series,
    get_prediction_assumptions,
    PREDICTION_DISCLAIMER,
    RISK_ORDER,
    RISK_DISPLAY,
)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 1: Core Formula — Arrival Rate Calculation")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

# 1.1 Simple positive rate
h = [FakeHistory(120, 0), FakeHistory(100, 4)]  # desc order (newest first)
rate, elapsed = _calculate_rate(h)
record(
    "Positive rate: +5 people/hr over 4h window",
    rate == 5.0 and abs(elapsed - 4.0) < 0.05,
    f"rate={rate}, elapsed={elapsed}"
)

# 1.2 Negative rate (people leaving)
h = [FakeHistory(60, 0), FakeHistory(100, 5)]
rate, elapsed = _calculate_rate(h)
record(
    "Negative rate: -8 people/hr (departure trend)",
    rate == -8.0,
    f"rate={rate}"
)

# 1.3 Zero rate (no change)
h = [FakeHistory(100, 0), FakeHistory(100, 3)]
rate, elapsed = _calculate_rate(h)
record(
    "Zero rate: stable occupancy over 3h",
    rate == 0.0,
    f"rate={rate}"
)

# 1.4 Fewer than 2 records -> rate = 0
h_single = [FakeHistory(80, 0)]
rate, elapsed = _calculate_rate(h_single)
record(
    "Single record -> rate=0, elapsed=0",
    rate == 0.0 and elapsed == 0.0,
    f"rate={rate}, elapsed={elapsed}"
)

# 1.5 Empty history -> rate = 0
rate, elapsed = _calculate_rate([])
record(
    "Empty history -> rate=0, elapsed=0",
    rate == 0.0 and elapsed == 0.0,
    f"rate={rate}"
)

# 1.6 Nearly-identical timestamps (< 1 minute) -> rate = 0 (guard)
h = [
    FakeHistory(110, 0),
    FakeHistory(100, 0.01),  # 0.01h = 0.6 minutes
]
rate, _ = _calculate_rate(h)
record(
    "Timestamps < 1 min apart -> rate=0 (floating-point guard)",
    rate == 0.0,
    f"rate={rate}"
)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 2: Risk Classification Thresholds")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

safe_limit = 85.0

RISK_CASES = [
    (0.0,   'low',      "0% -> low"),
    (59.9,  'low',      "59.9% -> low"),
    (60.0,  'moderate', "60.0% -> moderate"),
    (70.0,  'moderate', "70.0% -> moderate"),
    (84.9,  'moderate', "84.9% -> moderate"),
    (85.0,  'high',     "85.0% == safe_limit -> high"),
    (90.0,  'high',     "90.0% -> high"),
    (99.9,  'high',     "99.9% -> high"),
    (100.0, 'critical', "100.0% -> critical"),
    (110.0, 'critical', "110.0% -> critical (over max)"),
]

for pct, expected, label in RISK_CASES:
    got = _classify_risk(pct, safe_limit)
    record(
        f"_classify_risk({pct}%, safe={safe_limit}%) == '{expected}' [{label}]",
        got == expected,
        f"got '{got}'"
    )

# 2.x All risk levels have RISK_DISPLAY entries
for level in ('critical', 'high', 'moderate', 'low'):
    d = RISK_DISPLAY.get(level, {})
    record(
        f"RISK_DISPLAY['{level}'] has label, css, icon",
        bool(d.get('label')) and bool(d.get('css')) and bool(d.get('icon')),
        f"got {d}"
    )

# 2.x RISK_ORDER is monotonically increasing low -> critical
record(
    "RISK_ORDER: critical > high > moderate > low",
    RISK_ORDER['critical'] > RISK_ORDER['high'] > RISK_ORDER['moderate'] > RISK_ORDER['low'],
    f"order={RISK_ORDER}"
)


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 3: Forecast Formula + Edge Cases")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

# We test through generate_forecast_series which exercises the full formula
# (uses _load_history internally -> needs DB) so we use predict_shelter_occupancy
# with the Flask app context for DB-backed cases.

# First, test generate_forecast_series with a stub shelter
# (it calls _load_history which hits DB -> we need app context)

from app import create_app
from extensions import db, bcrypt
from models.user import User
from models.shelter import Shelter
from models.facility import ShelterFacility
from models.resource import Resource
from models.occupancy import OccupancyHistory

app = create_app()

with app.app_context():
    # Create a test shelter with known history for controlled formula tests
    Shelter.query.filter(Shelter.name.like('TestPred_%')).delete(synchronize_session=False)
    db.session.commit()

    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(
            email='pred_admin@shelter.test',
            full_name='Pred Test Admin',
            role='admin',
            password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8')
        )
        db.session.add(admin)
        db.session.commit()

    # 3.1 Controlled shelter: rate = +10/hr, 200 max
    sh_controlled = Shelter(
        name='TestPred_Controlled', address='Test Area',
        latitude=18.52, longitude=73.86,
        max_capacity=200, current_occupancy=100,
        status='active', safe_limit_pct=80
    )
    db.session.add(sh_controlled)
    db.session.flush()
    db.session.add(ShelterFacility(
        shelter_id=sh_controlled.id,
        has_wheelchair_access=True, has_medical_support=True,
        has_food=True, has_running_water=True, has_electricity=True,
        has_toilets=True, has_kitchen=False, has_family_area=False
    ))
    db.session.add(Resource(
        shelter_id=sh_controlled.id,
        beds_available=50, food_portions=200,
        water_litres=500, medicine_kits=10, blankets=50
    ))

    # Insert 5 history records simulating +10 people per hour
    now = datetime.utcnow()
    for i in range(5):
        db.session.add(OccupancyHistory(
            shelter_id=sh_controlled.id,
            occupancy=60 + i * 10,             # 60, 70, 80, 90, 100 (current=100)
            recorded_at=now - timedelta(hours=4 - i),
            recorded_by=admin.id
        ))
    db.session.commit()

    # Re-query the shelter
    sh = db.session.get(Shelter, sh_controlled.id)

    from services.prediction import predict_shelter_occupancy, generate_forecast_series

    # 3.1a Formula: current=100, rate=+10/hr over 4h, predict in 6h -> 160
    pred = predict_shelter_occupancy(sh, hours_ahead=6)
    record(
        "has_prediction=True when >= 2 records exist",
        pred['has_prediction'],
        f"got {pred['has_prediction']}"
    )
    record(
        "arrival_rate_per_hour = +10.0 (known controlled input)",
        pred['arrival_rate_per_hour'] == 10.0,
        f"got {pred['arrival_rate_per_hour']}"
    )
    record(
        "predicted_occupancy = 160 (100 + 10*6)",
        pred['predicted_occupancy'] == 160,
        f"got {pred['predicted_occupancy']}"
    )
    record(
        "predicted_pct = 80.0% (160/200*100)",
        pred['predicted_pct'] == 80.0,
        f"got {pred['predicted_pct']}"
    )
    record(
        "overload_risk = 'high' (80.0% == safe_limit 80%)",
        pred['overload_risk'] == 'high',
        f"got {pred['overload_risk']}"
    )

    # 3.1b Predict in 24h -> 100 + 10*24 = 340, clamped to 200 (max)
    pred_24 = predict_shelter_occupancy(sh, hours_ahead=24)
    record(
        "Occupancy clamped to max_capacity (200) when projection exceeds max",
        pred_24['predicted_occupancy'] == 200,
        f"got {pred_24['predicted_occupancy']}"
    )
    record(
        "Predicted_pct clamped to 100.0% when occupancy == max_capacity",
        pred_24['predicted_pct'] == 100.0,
        f"got {pred_24['predicted_pct']}"
    )
    record(
        "overload_risk = 'critical' at 100%",
        pred_24['overload_risk'] == 'critical',
        f"got {pred_24['overload_risk']}"
    )

    # 3.2 Declining shelter: negative arrival rate
    sh_declining = Shelter(
        name='TestPred_Declining', address='Declining Zone',
        latitude=18.53, longitude=73.87,
        max_capacity=200, current_occupancy=50,
        status='active', safe_limit_pct=85
    )
    db.session.add(sh_declining)
    db.session.flush()
    db.session.add(ShelterFacility(shelter_id=sh_declining.id))
    db.session.add(Resource(shelter_id=sh_declining.id, beds_available=100, food_portions=300,
                             water_litres=600, medicine_kits=15, blankets=60))

    # History: occupancy decreasing from 90 -> 50 over 4 hours (rate = -10/hr)
    for i in range(5):
        db.session.add(OccupancyHistory(
            shelter_id=sh_declining.id,
            occupancy=90 - i * 10,    # 90, 80, 70, 60, 50
            recorded_at=now - timedelta(hours=4 - i),
            recorded_by=admin.id
        ))
    db.session.commit()

    sh_dec = db.session.get(Shelter, sh_declining.id)
    pred_dec = predict_shelter_occupancy(sh_dec, hours_ahead=6)
    record(
        "Declining shelter: arrival_rate_per_hour = -10.0",
        pred_dec['arrival_rate_per_hour'] == -10.0,
        f"got {pred_dec['arrival_rate_per_hour']}"
    )
    record(
        "Declining shelter: predicted occupancy clamped to 0 (never negative)",
        pred_dec['predicted_occupancy'] >= 0,
        f"got {pred_dec['predicted_occupancy']}"
    )
    record(
        "Declining shelter: overload_risk is 'low'",
        pred_dec['overload_risk'] == 'low',
        f"got {pred_dec['overload_risk']}"
    )

    # 3.3 Shelter with no history -> stable baseline
    sh_nohistory = Shelter(
        name='TestPred_NoHistory', address='Empty Zone',
        latitude=18.54, longitude=73.88,
        max_capacity=200, current_occupancy=80,
        status='active', safe_limit_pct=85
    )
    db.session.add(sh_nohistory)
    db.session.flush()
    db.session.add(ShelterFacility(shelter_id=sh_nohistory.id))
    db.session.add(Resource(shelter_id=sh_nohistory.id, beds_available=80, food_portions=200,
                             water_litres=400, medicine_kits=10, blankets=40))
    db.session.commit()

    sh_nh = db.session.get(Shelter, sh_nohistory.id)
    pred_nh = predict_shelter_occupancy(sh_nh, hours_ahead=6)
    record(
        "No history: has_prediction=False",
        pred_nh['has_prediction'] == False,
        f"got {pred_nh['has_prediction']}"
    )
    record(
        "No history: predicted_occupancy = current_occupancy (stable flat)",
        pred_nh['predicted_occupancy'] == sh_nh.current_occupancy,
        f"got {pred_nh['predicted_occupancy']}"
    )
    record(
        "No history: arrival_rate_per_hour = 0.0",
        pred_nh['arrival_rate_per_hour'] == 0.0,
        f"got {pred_nh['arrival_rate_per_hour']}"
    )


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 4: Forecast Series Shape & Values")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    sh = Shelter.query.filter_by(name='TestPred_Controlled').first()
    if sh:
        series = generate_forecast_series(sh, hours_ahead=6, steps=12)

        record(
            "Series length = steps + 1 (13 points for steps=12)",
            len(series) == 13,
            f"got {len(series)}"
        )
        record(
            "First point: hour=0.0 (t=now)",
            series[0]['hour'] == 0.0,
            f"got {series[0]['hour']}"
        )
        record(
            "First point: is_actual=True",
            series[0]['is_actual'] == True,
            f"got {series[0]['is_actual']}"
        )
        record(
            "All subsequent points: is_actual=False",
            all(not p['is_actual'] for p in series[1:]),
            f"found actual flags: {[p['is_actual'] for p in series[1:]]}"
        )
        record(
            "Last point: hour == hours_ahead (6.0)",
            series[-1]['hour'] == 6.0,
            f"got {series[-1]['hour']}"
        )
        record(
            "All occupancy values >= 0",
            all(p['occupancy'] >= 0 for p in series),
            f"min occupancy: {min(p['occupancy'] for p in series)}"
        )
        record(
            "All pct values >= 0 and <= 100 (clamped at max)",
            all(0 <= p['pct'] <= 100 for p in series),
            f"pct range: {min(p['pct'] for p in series)} - {max(p['pct'] for p in series)}"
        )
        record(
            "Series is monotonically non-decreasing (positive rate)",
            all(series[i]['occupancy'] <= series[i+1]['occupancy'] for i in range(len(series)-1)),
            "series is not monotonically non-decreasing"
        )


# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 64)
print("Suite 5: Batch predict_all_shelters()")
print("=" * 64)
# ═════════════════════════════════════════════════════════════════════════════

with app.app_context():
    from services.prediction import predict_all_shelters

    result = predict_all_shelters(hours_ahead=6)

    record("Result has 'hours_ahead' key", 'hours_ahead' in result)
    record("hours_ahead == 6", result['hours_ahead'] == 6, f"got {result['hours_ahead']}")
    record("Result has 'shelters' list", isinstance(result['shelters'], list))
    record("Result has 'risk_counts' dict", isinstance(result['risk_counts'], dict))
    record("Result has 'disclaimer' string", bool(result.get('disclaimer')))
    record("Result has 'generated_at' string", bool(result.get('generated_at')))

    # Risk count totals must equal number of shelters
    total_by_risk = sum(result['risk_counts'].values())
    record(
        "Sum of risk_counts == total shelters evaluated",
        total_by_risk == len(result['shelters']),
        f"sum={total_by_risk}, shelters={len(result['shelters'])}"
    )

    # Each shelter entry must have 'shelter' key (ORM object) + prediction keys
    required_keys = {
        'shelter', 'has_prediction', 'current_occupancy', 'arrival_rate_per_hour',
        'predicted_occupancy', 'predicted_pct', 'overload_risk', 'risk_label',
        'risk_display', 'records_used', 'summary', 'disclaimer', 'assumptions',
    }
    for p in result['shelters']:
        missing = required_keys - set(p.keys())
        if missing:
            record(f"All required keys present in shelter entry '{p['shelter'].name}'",
                   False, f"missing: {missing}")
            break
    else:
        record("All required keys present in every shelter entry", True)

    # Sorting: should be critical >= high >= moderate >= low
    risks = [p['overload_risk'] for p in result['shelters']]
    order_vals = [RISK_ORDER.get(r, 0) for r in risks]
    record(
        "Shelters sorted by risk descending (critical first)",
        all(order_vals[i] >= order_vals[i+1] for i in range(len(order_vals)-1)),
        f"order values: {order_vals}"
    )

# =============================================================================
print("\n" + "=" * 64)
print("Suite 6: API Endpoints (HTTP Integration)")
print("=" * 64)
# =============================================================================

with app.app_context():
    import json

    # Ensure admin user exists with known password
    admin_user = User.query.filter_by(role='admin').first()
    if not admin_user:
        admin_user = User(
            email='admin@shelter.gov',
            full_name='System Administrator',
            role='admin',
            password_hash=bcrypt.generate_password_hash('Password@123').decode('utf-8')
        )
        db.session.add(admin_user)
        db.session.commit()
    else:
        admin_user.password_hash = bcrypt.generate_password_hash('Password@123').decode('utf-8')
        db.session.commit()

    # Re-create test shelter if needed (cleanup may have removed it)
    sh_test = Shelter.query.filter_by(name='TestPred_Controlled').first()
    if not sh_test:
        sh_test = Shelter(
            name='TestPred_Controlled', address='Test Area',
            latitude=18.52, longitude=73.86,
            max_capacity=200, current_occupancy=100,
            status='active', safe_limit_pct=80
        )
        db.session.add(sh_test)
        db.session.flush()
        db.session.add(ShelterFacility(
            shelter_id=sh_test.id,
            has_wheelchair_access=True, has_medical_support=True,
            has_food=True, has_running_water=True, has_electricity=True,
            has_toilets=True, has_kitchen=False, has_family_area=False
        ))
        db.session.add(Resource(
            shelter_id=sh_test.id, beds_available=50, food_portions=200,
            water_litres=500, medicine_kits=10, blankets=50
        ))
        db.session.commit()
        sh_test = Shelter.query.filter_by(name='TestPred_Controlled').first()

    # The test client MUST be created fresh and kept for the whole suite
    client = app.test_client()

    # 6.0 Unauthenticated -> redirect
    resp_unauth = client.get('/predict/')
    record("Unauthenticated GET /predict/ -> 302 redirect",
           resp_unauth.status_code == 302, f"status={resp_unauth.status_code}")

    # Login with admin credentials
    login_resp = client.post('/auth/login', data={
        'email': admin_user.email,
        'password': 'Password@123'
    }, follow_redirects=True)
    record("Admin login for HTTP tests",
           login_resp.status_code == 200, f"status={login_resp.status_code}")

    # 6.1 GET /predict/
    resp = client.get('/predict/')
    record("GET /predict/ returns 200 OK", resp.status_code == 200, f"status={resp.status_code}")
    html = resp.data.decode('utf-8', errors='replace')
    record("Dashboard contains 'ESTIMATE' label", 'ESTIMATE' in html, "not found in html")
    record("Dashboard contains 'Forecast' heading", 'Forecast' in html, "not found")
    record("Dashboard contains risk counts", 'Critical' in html or 'Low' in html, "not found")
    record("Dashboard contains disclaimer text", 'ESTIMATE' in html or 'Heuristic' in html, "not found")

    # 6.2 Hours filter
    resp = client.get('/predict/?hours=24')
    record("GET /predict/?hours=24 returns 200 OK",
           resp.status_code == 200, f"status={resp.status_code}")

    # 6.3 Shelter forecast page
    resp = client.get(f'/predict/{sh_test.id}')
    record("GET /predict/<id> returns 200 OK", resp.status_code == 200, f"status={resp.status_code}")
    fc_html = resp.data.decode('utf-8', errors='replace')
    record("Shelter forecast page contains chart canvas", 'forecastChart' in fc_html, "not found")
    record("Shelter forecast page contains assumption disclosure",
           'Assumptions' in fc_html or 'assumption' in fc_html.lower(), "not found")
    record("Shelter forecast page contains [ESTIMATE]", 'ESTIMATE' in fc_html, "not found")

    # 6.4 API: /predict/api/all
    resp = client.get('/predict/api/all')
    record("GET /predict/api/all returns 200 OK", resp.status_code == 200, f"status={resp.status_code}")
    if resp.status_code == 200:
        data = json.loads(resp.data)
        record("API /all has 'hours_ahead' key", 'hours_ahead' in data)
        record("API /all has 'shelters' list", isinstance(data.get('shelters'), list))
        record("API /all has 'risk_counts' dict", isinstance(data.get('risk_counts'), dict))
        record("API /all has 'disclaimer' string", bool(data.get('disclaimer')))
        if data.get('shelters'):
            s0 = data['shelters'][0]
            for key in ('shelter_id', 'name', 'arrival_rate_per_hour',
                        'predicted_occupancy', 'predicted_pct', 'overload_risk',
                        'has_prediction', 'assumptions'):
                record(f"API /all entry has '{key}'", key in s0)

    # 6.5 Hours param
    resp = client.get('/predict/api/all?hours=12')
    record("GET /predict/api/all?hours=12 returns 200 OK",
           resp.status_code == 200, f"status={resp.status_code}")
    if resp.status_code == 200:
        data = json.loads(resp.data)
        record("API /all?hours=12 reports hours_ahead=12",
               data.get('hours_ahead') == 12, f"got {data.get('hours_ahead')}")

    # 6.6 Single shelter API
    resp = client.get(f'/predict/api/{sh_test.id}')
    record("GET /predict/api/<id> returns 200 OK",
           resp.status_code == 200, f"status={resp.status_code}")
    if resp.status_code == 200:
        sdata = json.loads(resp.data)
        record("Single API has 'forecast_series' list",
               isinstance(sdata.get('forecast_series'), list))
        series_len = len(sdata.get('forecast_series', []))
        record(f"forecast_series has > 1 point ({series_len})", series_len > 1)
        record("First series point has is_actual=true",
               sdata['forecast_series'][0].get('is_actual') == True if series_len else False)
        record("Single API has 'assumptions' dict", isinstance(sdata.get('assumptions'), dict))
        record("Single API has 'disclaimer' string", bool(sdata.get('disclaimer')))

    # 6.7 404 for unknown shelter
    resp = client.get('/predict/api/99999999')
    record("GET /predict/api/99999999 returns 404",
           resp.status_code == 404, f"status={resp.status_code}")

    # Cleanup
    Shelter.query.filter(Shelter.name.like('TestPred_%')).delete(synchronize_session=False)
    db.session.commit()


# =============================================================================
print("\n" + "=" * 64)
print(f"Total Tests Run : {total_tests}")
print(f"Passed          : {passed_tests}")
print(f"Failed          : {total_tests - passed_tests}")
print("=" * 64)

if __name__ == '__main__':
    sys.exit(0 if total_tests == passed_tests else 1)

