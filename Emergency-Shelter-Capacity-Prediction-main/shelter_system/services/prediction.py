"""
services/prediction.py — MVP Occupancy Prediction Engine.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMPORTANT — All output from this module is a HEURISTIC ESTIMATE.
It is NOT guaranteed, NOT a real-time sensor, and MUST NOT be used
as the sole basis for critical life-safety decisions.
Clearly label every predicted value as [ESTIMATE] in any UI or API.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MVP FORMULA (no machine learning):

    Arrival Rate (people/hour) =
        (occupancy[newest_record] - occupancy[oldest_record])
        ──────────────────────────────────────────────────────
               elapsed time (hours) between those records

    Predicted Future Occupancy =
        Current Occupancy + (Arrival Rate × Hours Ahead)
        → clamped to [0, max_capacity]

    Predicted Occupancy % =
        (Predicted Future Occupancy / Max Capacity) × 100

    Overload Risk:
        critical  → Predicted % >= 100
        high      → Predicted % >= safe_limit %   (default 85%)
        moderate  → Predicted % >= 60
        low       → Predicted % <  60

ASSUMPTIONS DISCLOSED:
    - Uses the most recent 10 occupancy history records (configurable).
    - Calculates a simple linear rate from oldest→newest in that window.
    - Ignores time-of-day seasonality, external event effects, or weather.
    - If fewer than 2 distinct history records exist, rate is assumed 0 (stable).
    - Rate is not floored at 0 — a declining trend (negative rate) is valid
      and results in a lower predicted occupancy.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional

from models.occupancy import OccupancyHistory


# ── Constants ─────────────────────────────────────────────────────────────────

PREDICTION_DISCLAIMER = (
    "[ESTIMATE] Heuristic forecast using simple linear rate extrapolation "
    "from recent occupancy history. Not a real-time sensor. "
    "Not guaranteed to be accurate. Verify on-ground conditions before dispatch."
)

# Number of most recent history records used for rate calculation
HISTORY_WINDOW = 10

# Risk level ordering for sorting (higher index = higher priority)
RISK_ORDER = {'critical': 4, 'high': 3, 'moderate': 2, 'low': 1}

RISK_DISPLAY = {
    'critical': {'label': 'Critical Overload Risk',   'css': 'danger',  'icon': 'bi-exclamation-octagon-fill'},
    'high':     {'label': 'High Risk (Near Limit)',   'css': 'warning', 'icon': 'bi-exclamation-triangle-fill'},
    'moderate': {'label': 'Moderate Load',            'css': 'info',    'icon': 'bi-info-circle-fill'},
    'low':      {'label': 'Low Risk (Stable)',        'css': 'success', 'icon': 'bi-check-circle-fill'},
}


# ── Config helpers ────────────────────────────────────────────────────────────

def get_default_forecast_hours() -> int:
    """Read forecast horizon in hours from Flask config, default 6."""
    try:
        from flask import current_app
        if current_app and 'PREDICT_HOURS_AHEAD' in current_app.config:
            return int(current_app.config['PREDICT_HOURS_AHEAD'])
    except Exception:
        pass
    return 6


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_history(shelter_id: int, window: int = HISTORY_WINDOW) -> List:
    """Fetch the most recent `window` occupancy records for a shelter."""
    try:
        return (
            OccupancyHistory.query
            .filter_by(shelter_id=shelter_id)
            .order_by(OccupancyHistory.recorded_at.desc())
            .limit(window)
            .all()
        )
    except Exception:
        return []



def _calculate_rate(history: List) -> tuple[float, float]:
    """
    Compute arrival rate (people/hour) from an ordered history list (desc).

    Returns:
        (rate_per_hour, elapsed_hours)
        rate_per_hour: positive = arriving, negative = leaving, 0.0 = stable
        elapsed_hours: time span of the sample window in hours
    """
    if len(history) < 2:
        return 0.0, 0.0

    newest = history[0]
    oldest = history[-1]

    elapsed_h = (newest.recorded_at - oldest.recorded_at).total_seconds() / 3600.0

    # Guard against identical or nearly-identical timestamps (< 1 minute apart)
    if elapsed_h < (1 / 60):
        return 0.0, 0.0

    rate = (newest.occupancy - oldest.occupancy) / elapsed_h
    return round(rate, 2), round(elapsed_h, 2)


def _classify_risk(predicted_pct: float, safe_limit: float) -> str:
    """Return overload risk string based on predicted occupancy percentage."""
    if predicted_pct >= 100.0:
        return 'critical'
    if predicted_pct >= safe_limit:
        return 'high'
    if predicted_pct >= 60.0:
        return 'moderate'
    return 'low'


# ── Public API ────────────────────────────────────────────────────────────────

def get_prediction_assumptions(shelter, history: List) -> Dict[str, Any]:
    """
    Return a structured dictionary describing every assumption the prediction
    engine made for this shelter.  Always shown to the user — never hidden.

    This is the transparency/explainability layer: the user can see exactly
    what data was used and what simplifications were applied.
    """
    n = len(history)
    _, elapsed_h = _calculate_rate(history)

    if n >= 2:
        newest = history[0]
        oldest = history[-1]
        window_desc = (
            f"Last {n} occupancy records spanning "
            f"~{elapsed_h:.1f} hours "
            f"({oldest.recorded_at.strftime('%d %b %H:%M')} to "
            f"{newest.recorded_at.strftime('%d %b %H:%M')} UTC)"
        )
        method = "Simple linear rate: (newest occupancy - oldest occupancy) / elapsed hours"
    else:
        window_desc = f"Only {n} record(s) found — arrival rate set to 0 (stable baseline assumed)"
        method = "No trend calculable; current occupancy used as flat forecast"

    return {
        'data_window':       window_desc,
        'records_used':      n,
        'method':            method,
        'seasonality':       'Not modelled — time-of-day and day-of-week patterns ignored',
        'external_factors':  'Not modelled — weather, events, and alerts not considered',
        'ml':                'No machine learning — pure arithmetic rate extrapolation',
        'safe_limit_pct':    shelter.safe_limit,
        'max_capacity':      shelter.max_capacity,
        'current_occupancy': shelter.current_occupancy,
        'disclaimer':        PREDICTION_DISCLAIMER,
    }


def predict_shelter_occupancy(shelter, hours_ahead: Optional[int] = None) -> Dict[str, Any]:
    """
    Core prediction function: estimates occupancy at `hours_ahead` from now.

    Formula:
        rate       = (newest_occ - oldest_occ) / elapsed_hours
        predicted  = max(0, current_occ + rate × hours_ahead)
        predicted% = predicted / max_capacity × 100

    Args:
        shelter:     Shelter model instance.
        hours_ahead: Forecast horizon in hours (defaults to config PREDICT_HOURS_AHEAD).

    Returns:
        Dict with:
          has_prediction        bool    — True if rate was calculable
          current_occupancy     int
          arrival_rate_per_hour float   — people/hr (negative = declining)
          hours_ahead           int
          predicted_occupancy   int     — [ESTIMATE]
          predicted_pct         float   — [ESTIMATE]
          overload_risk         str     — low/moderate/high/critical
          risk_label            str
          risk_display          dict    — css class, icon, label
          elapsed_hours         float   — window span used for rate
          records_used          int
          summary               str
          disclaimer            str
          assumptions           dict    — full assumption disclosure
    """
    if hours_ahead is None:
        hours_ahead = get_default_forecast_hours()
    hours_ahead = max(1, int(hours_ahead))

    history  = _load_history(shelter.id)
    rate, elapsed_h = _calculate_rate(history)

    curr_occ = shelter.current_occupancy
    max_cap  = shelter.max_capacity
    safe_lim = shelter.safe_limit    # effective safe limit %

    has_prediction = (len(history) >= 2 and elapsed_h > 0)

    # Predict future occupancy, clamp to [0, max_cap]
    raw_predicted  = curr_occ + (rate * hours_ahead)
    predicted      = int(round(max(0, min(max_cap, raw_predicted))))
    predicted_pct  = round((predicted / max_cap * 100.0), 1) if max_cap > 0 else 0.0

    overload_risk  = _classify_risk(predicted_pct, safe_lim)
    risk_disp      = RISK_DISPLAY.get(overload_risk, RISK_DISPLAY['low'])

    if has_prediction:
        risk_label = f"{risk_disp['label']} — {predicted_pct}% in {hours_ahead}h"
        summary    = (
            f"Rate: {rate:+.1f} people/hr over {elapsed_h:.1f}h sample "
            f"-> Est. {predicted} people ({predicted_pct}%) in {hours_ahead}h"
        )
    else:
        risk_label = f"{risk_disp['label']} (stable baseline — no trend data)"
        summary    = f"No trend calculable; current occupancy {curr_occ} used as flat estimate"

    return {
        'has_prediction':        has_prediction,
        'current_occupancy':     curr_occ,
        'arrival_rate_per_hour': rate,
        'hours_ahead':           hours_ahead,
        'predicted_occupancy':   predicted,
        'predicted_pct':         predicted_pct,
        'overload_risk':         overload_risk,
        'risk_label':            risk_label,
        'risk_display':          risk_disp,
        'elapsed_hours':         elapsed_h,
        'records_used':          len(history),
        'summary':               summary,
        'disclaimer':            PREDICTION_DISCLAIMER,
        'assumptions':           get_prediction_assumptions(shelter, history),
    }


def generate_forecast_series(
    shelter,
    hours_ahead: int = 6,
    steps: int = 12,
) -> List[Dict[str, Any]]:
    """
    Generate a time-series of predicted occupancy points for Chart.js.

    Produces `steps + 1` evenly-spaced points from t=0 (now) to t=hours_ahead.
    Point at t=0 always uses the actual current occupancy (not predicted).

    Returns:
        List of dicts:
          hour        float  — hours from now (0.0 … hours_ahead)
          occupancy   int    — predicted headcount at that hour [ESTIMATE except t=0]
          pct         float  — predicted % of max_capacity [ESTIMATE except t=0]
          is_actual   bool   — True only for t=0 (the real current data point)
    """
    hours_ahead = max(1, int(hours_ahead))
    steps       = max(2, int(steps))

    history   = _load_history(shelter.id)
    rate, _   = _calculate_rate(history)

    curr_occ = shelter.current_occupancy
    max_cap  = shelter.max_capacity

    interval = hours_ahead / steps
    series   = []

    for i in range(steps + 1):
        h         = round(i * interval, 2)
        raw_occ   = curr_occ + (rate * h)
        occ       = int(round(max(0, min(max_cap, raw_occ))))
        pct       = round((occ / max_cap * 100.0), 1) if max_cap > 0 else 0.0
        series.append({
            'hour':      h,
            'occupancy': occ,
            'pct':       pct,
            'is_actual': (i == 0),
        })

    return series


def predict_all_shelters(
    hours_ahead: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run occupancy prediction for EVERY shelter and return a sorted summary.

    Sorted by risk severity (critical first), then by predicted_pct desc.

    Returns:
        {
          'hours_ahead':  int,
          'shelters':     list of prediction dicts (each has 'shelter' key added),
          'risk_counts':  {'critical': N, 'high': N, 'moderate': N, 'low': N},
          'disclaimer':   str,
        }
    """
    from models.shelter import Shelter

    if hours_ahead is None:
        hours_ahead = get_default_forecast_hours()
    hours_ahead = max(1, int(hours_ahead))

    all_shelters = Shelter.query.order_by(Shelter.name).all()

    results      = []
    risk_counts  = {'critical': 0, 'high': 0, 'moderate': 0, 'low': 0}

    for shelter in all_shelters:
        pred = predict_shelter_occupancy(shelter, hours_ahead=hours_ahead)
        pred['shelter'] = shelter
        results.append(pred)
        risk_counts[pred['overload_risk']] += 1

    # Sort: critical first, then by predicted_pct descending
    results.sort(
        key=lambda p: (-RISK_ORDER.get(p['overload_risk'], 0), -p['predicted_pct'])
    )

    return {
        'hours_ahead': hours_ahead,
        'shelters':    results,
        'risk_counts': risk_counts,
        'disclaimer':  PREDICTION_DISCLAIMER,
        'generated_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
    }
