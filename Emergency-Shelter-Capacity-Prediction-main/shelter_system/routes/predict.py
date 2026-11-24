"""
routes/predict.py — Occupancy Prediction Engine routes.

All predicted values are ESTIMATES — labelled [ESTIMATE] in templates and API.

Routes:
  GET  /predict/                        — Network prediction dashboard
  GET  /predict/<shelter_id>            — Per-shelter detailed forecast
  GET  /predict/api/all                 — JSON: all shelter predictions
  GET  /predict/api/<shelter_id>        — JSON: single shelter + time-series

Query parameters:
  ?hours=N   (int, 1–72)   — forecast horizon in hours  (default: config / 6)

Access:
  All routes require login. No further role restriction — prediction data is
  informational and appropriate for all authenticated roles.
"""

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required

from models.shelter import Shelter
from services.prediction import (
    predict_shelter_occupancy,
    predict_all_shelters,
    generate_forecast_series,
    get_default_forecast_hours,
    PREDICTION_DISCLAIMER,
)

predict_bp = Blueprint('predict', __name__)

# Allowed hours values for the selector (prevent arbitrary large values)
ALLOWED_HOURS = [1, 3, 6, 12, 24, 48]
DEFAULT_STEPS  = 24   # Chart.js data points across the forecast window


def _parse_hours(raw: str | None) -> int:
    """Parse and clamp the ?hours= query param to an allowed value."""
    try:
        h = int(raw or get_default_forecast_hours())
    except (TypeError, ValueError):
        h = get_default_forecast_hours()
    # Snap to nearest allowed value
    return min(ALLOWED_HOURS, key=lambda a: abs(a - h))


# ─────────────────────────────────────────────────────────────────────────────
# UI Routes
# ─────────────────────────────────────────────────────────────────────────────

@predict_bp.route('/', methods=['GET'])
@login_required
def prediction_dashboard():
    """
    Network-wide occupancy prediction dashboard.

    Shows all shelters sorted by risk severity (critical first) with their
    predicted occupancy at the selected forecast horizon.
    """
    hours = _parse_hours(request.args.get('hours'))
    batch = predict_all_shelters(hours_ahead=hours)

    return render_template(
        'predict/dashboard.html',
        batch=batch,
        hours=hours,
        allowed_hours=ALLOWED_HOURS,
        default_hours=get_default_forecast_hours(),
    )


@predict_bp.route('/<int:shelter_id>', methods=['GET'])
@login_required
def shelter_forecast(shelter_id: int):
    """
    Per-shelter detailed forecast page with Chart.js visualisation.

    Shows:
    - Current occupancy and safe/max thresholds
    - [ESTIMATE] predicted occupancy at selected horizon
    - Chart.js line chart: actual (t=0) + dashed forecast line
    - Assumption disclosure panel (always visible)
    - Last N occupancy history records used in calculation
    """
    shelter = Shelter.query.get_or_404(shelter_id)
    hours   = _parse_hours(request.args.get('hours'))

    pred    = predict_shelter_occupancy(shelter, hours_ahead=hours)
    series  = generate_forecast_series(shelter, hours_ahead=hours, steps=DEFAULT_STEPS)

    # History records for the "data used" table (most recent HISTORY_WINDOW records)
    from models.occupancy import OccupancyHistory
    history = (
        OccupancyHistory.query
        .filter_by(shelter_id=shelter_id)
        .order_by(OccupancyHistory.recorded_at.desc())
        .limit(10)
        .all()
    )

    # Build Chart.js-ready data (convert to plain dicts for JSON serialisation in template)
    chart_labels  = [f"+{p['hour']:.1f}h" for p in series]
    chart_occ     = [p['occupancy'] for p in series]
    chart_pct     = [p['pct'] for p in series]
    chart_actual_idx = 0  # index of the real (non-estimated) point

    return render_template(
        'predict/shelter_forecast.html',
        shelter=shelter,
        pred=pred,
        series=series,
        history=history,
        hours=hours,
        allowed_hours=ALLOWED_HOURS,
        chart_labels=chart_labels,
        chart_occ=chart_occ,
        chart_pct=chart_pct,
        chart_actual_idx=chart_actual_idx,
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSON API Routes
# ─────────────────────────────────────────────────────────────────────────────

@predict_bp.route('/api/all', methods=['GET'])
@login_required
def api_predict_all():
    """
    JSON — prediction for all shelters at given horizon.

    Response:
    {
      "hours_ahead":  6,
      "generated_at": "2026-09-13 08:30 UTC",
      "disclaimer":   "...",
      "risk_counts":  {"critical": 1, "high": 2, "moderate": 3, "low": 5},
      "shelters": [
        {
          "shelter_id":            1,
          "name":                  "Shelter A",
          "current_occupancy":     120,
          "arrival_rate_per_hour": 4.5,
          "predicted_occupancy":   147,
          "predicted_pct":         73.5,
          "overload_risk":         "moderate",
          "risk_label":            "Moderate Load — 73.5% in 6h",
          "has_prediction":        true,
          "records_used":          8,
          "elapsed_hours":         5.2,
          "summary":               "...",
          "assumptions":           { ... }
        },
        ...
      ]
    }
    """
    hours  = _parse_hours(request.args.get('hours'))
    batch  = predict_all_shelters(hours_ahead=hours)

    # Strip ORM objects for JSON serialisation
    shelters_out = []
    for p in batch['shelters']:
        s = p['shelter']
        shelters_out.append({
            'shelter_id':            s.id,
            'name':                  s.name,
            'address':               s.address,
            'status':                s.status,
            'max_capacity':          s.max_capacity,
            'current_occupancy':     p['current_occupancy'],
            'safe_limit_pct':        s.safe_limit,
            'arrival_rate_per_hour': p['arrival_rate_per_hour'],
            'hours_ahead':           p['hours_ahead'],
            'predicted_occupancy':   p['predicted_occupancy'],
            'predicted_pct':         p['predicted_pct'],
            'overload_risk':         p['overload_risk'],
            'risk_label':            p['risk_label'],
            'has_prediction':        p['has_prediction'],
            'records_used':          p['records_used'],
            'elapsed_hours':         p['elapsed_hours'],
            'summary':               p['summary'],
            'assumptions':           p['assumptions'],
        })

    return jsonify({
        'hours_ahead':  batch['hours_ahead'],
        'generated_at': batch['generated_at'],
        'disclaimer':   batch['disclaimer'],
        'risk_counts':  batch['risk_counts'],
        'shelters':     shelters_out,
    })


@predict_bp.route('/api/<int:shelter_id>', methods=['GET'])
@login_required
def api_predict_shelter(shelter_id: int):
    """
    JSON — detailed prediction for one shelter including forecast time-series.

    Response:
    {
      "shelter_id":            1,
      "name":                  "Shelter A",
      "current_occupancy":     120,
      "arrival_rate_per_hour": 4.5,
      "hours_ahead":           6,
      "predicted_occupancy":   147,
      "predicted_pct":         73.5,
      "overload_risk":         "moderate",
      "risk_label":            "...",
      "has_prediction":        true,
      "records_used":          8,
      "elapsed_hours":         5.2,
      "disclaimer":            "...",
      "assumptions":           { ... },
      "forecast_series": [
        {"hour": 0.0,  "occupancy": 120, "pct": 60.0, "is_actual": true},
        {"hour": 0.25, "occupancy": 121, "pct": 60.5, "is_actual": false},
        ...
      ]
    }
    """
    shelter = Shelter.query.get_or_404(shelter_id)
    hours   = _parse_hours(request.args.get('hours'))

    pred   = predict_shelter_occupancy(shelter, hours_ahead=hours)
    series = generate_forecast_series(shelter, hours_ahead=hours, steps=DEFAULT_STEPS)

    return jsonify({
        'shelter_id':            shelter.id,
        'name':                  shelter.name,
        'address':               shelter.address,
        'max_capacity':          shelter.max_capacity,
        'safe_limit_pct':        shelter.safe_limit,
        'current_occupancy':     pred['current_occupancy'],
        'arrival_rate_per_hour': pred['arrival_rate_per_hour'],
        'hours_ahead':           pred['hours_ahead'],
        'predicted_occupancy':   pred['predicted_occupancy'],
        'predicted_pct':         pred['predicted_pct'],
        'overload_risk':         pred['overload_risk'],
        'risk_label':            pred['risk_label'],
        'has_prediction':        pred['has_prediction'],
        'records_used':          pred['records_used'],
        'elapsed_hours':         pred['elapsed_hours'],
        'summary':               pred['summary'],
        'disclaimer':            pred['disclaimer'],
        'assumptions':           pred['assumptions'],
        'forecast_series':       series,
    })
