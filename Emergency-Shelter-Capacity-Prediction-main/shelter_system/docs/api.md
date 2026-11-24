# REST JSON API Documentation

This document describes the JSON API endpoints exposed by the **Emergency Shelter Capacity Prediction and Redistribution System**. These endpoints provide programmatic access for mobile responder units, external situational dashboards, and automated telemetry.

---

## Authentication & Headers

- **Authentication**: Endpoints require an active session cookie (`session=...`) obtained by authenticating at `/auth/login`.
- **Role Permissions**: Read-only APIs require standard user authentication. Action APIs require `responder`, `authority`, or `admin` roles.
- **CSRF Token**: State-mutating POST requests require an `X-CSRFToken` header or form body `csrf_token` when CSRF protection is enabled.

---

## 1. Dashboard Telemetry API

### `GET /dashboard/api/stats`
Returns aggregated real-time metrics across all shelters and alert counts for high-density dashboards and external displays.

- **Access**: All authenticated users (`@login_required`)
- **Query Parameters**:
  - `hours` *(optional, integer, default: 6)*: Forecast horizon to compute predicted overloads.

#### Response: `200 OK`
```json
{
  "total_shelters": 12,
  "active_shelters": 10,
  "inactive_shelters": 2,
  "total_capacity": 2400,
  "current_occupancy": 1420,
  "occupancy_pct": 59.2,
  "safe_available_headroom": 620,
  "critical_shelters_count": 2,
  "overcrowded_shelters_count": 0,
  "predicted_overloads_count": 1,
  "resource_shortages_count": 3,
  "active_alerts_count": 5,
  "unread_alerts_count": 2,
  "forecast_hours": 6,
  "chart_labels": ["Community Hall", "Sports Complex", "West High School"],
  "chart_occupancy": [180, 450, 220],
  "chart_safe_capacity": [212, 425, 255],
  "chart_max_capacity": [250, 500, 300]
}
```

---

## 2. Recommendation Engine API

### `GET /recommend/api/request/<int:request_id>`
Evaluates candidate shelters for a specific emergency request and returns the top recommendation, scoring breakdown, and rejection reasons.

- **Access**: `responder`, `admin`
- **URL Parameters**:
  - `request_id` *(integer, required)*: ID of the pending `ShelterRequest`.

#### Response: `200 OK`
```json
{
  "request_id": 14,
  "group_size": 35,
  "recommended_shelter": {
    "shelter_id": 3,
    "shelter_name": "Central Sports Arena",
    "total_score": 88.4,
    "distance_km": 3.2,
    "positive_reasons": [
      "Closest eligible facility (3.2 km)",
      "Ample safe capacity headroom (145 spots available)",
      "Full wheelchair access & on-site medical triage",
      "Adequate drinking water stock"
    ]
  },
  "total_eligible": 4,
  "total_rejected": 2,
  "disclaimer": "Recommendations are explainable decision-support proposals. Final placement remains with human dispatchers."
}
```

#### Error Responses:
- `404 Not Found`: Request ID does not exist.
- `403 Forbidden`: User does not possess responder privileges.

---

## 3. Redistribution Engine API

### `GET /recommend/api/redistribute/<int:request_id>`
Evaluates a multi-shelter partitioning plan when an incoming crowd cannot safely fit into a single shelter.

- **Access**: `responder`, `admin`
- **URL Parameters**:
  - `request_id` *(integer, required)*: ID of the pending `ShelterRequest`.
- **Query Parameters**:
  - `hours` *(optional, integer, default: 6)*: Prediction horizon for evaluating future capacity.

#### Response: `200 OK`
```json
{
  "request_id": 18,
  "group_size": 100,
  "is_possible": true,
  "total_requested": 100,
  "total_allocated": 100,
  "unallocated_count": 0,
  "total_network_safe_capacity": 145,
  "allocations": [
    {
      "shelter_id": 2,
      "shelter_name": "Kothrud Community Center",
      "allocated_count": 45,
      "current_occupancy": 80,
      "safe_capacity": 125,
      "max_capacity": 150,
      "safe_available_before": 45,
      "safe_available_after": 0,
      "projected_occupancy": 125,
      "projected_pct": 83.3,
      "distance_km": 2.4,
      "score": 91.2,
      "rank": 1,
      "reasons": ["Allocated up to full safe limit (45 people)", "Closest facility (2.4 km)"]
    },
    {
      "shelter_id": 5,
      "shelter_name": "Shivajinagar Relief Camp",
      "allocated_count": 55,
      "current_occupancy": 110,
      "safe_capacity": 170,
      "max_capacity": 200,
      "safe_available_before": 60,
      "safe_available_after": 5,
      "projected_occupancy": 165,
      "projected_pct": 82.5,
      "distance_km": 4.8,
      "score": 84.6,
      "rank": 2,
      "reasons": ["Allocated remaining 55 people safely", "Maintains 5 headroom spots"]
    }
  ],
  "candidate_shelters": [
    {
      "shelter_id": 2,
      "name": "Kothrud Community Center",
      "safe_available_capacity": 45,
      "score": 91.2,
      "rank": 1,
      "distance_km": 2.4
    }
  ],
  "unsuitable_shelters": [
    {
      "shelter_id": 8,
      "name": "Old Schoolhouse",
      "reason": "Shelter is currently marked as damaged/inactive",
      "category": "Status Ineligible"
    }
  ],
  "explanation": "Group of 100 successfully partitioned across 2 shelters without exceeding safe limits.",
  "disclaimer": "Plan is deferred; occupancies will NOT update until explicitly confirmed."
}
```

---

## 4. Prediction Engine API

### `GET /predict/api/all`
Returns forecasted occupancies and risk levels across all shelters for a given time window.

- **Access**: All authenticated users (`@login_required`)
- **Query Parameters**:
  - `hours` *(optional, integer, allowed: 1, 3, 6, 12, 24, 48, default: 6)*

#### Response: `200 OK`
```json
{
  "forecast_hours": 6,
  "disclaimer": "[ESTIMATE: Projections assume current arrival trends continue. Verify with shelter staff.]",
  "predictions": [
    {
      "shelter_id": 1,
      "name": "City Sports Complex",
      "max_capacity": 500,
      "current_occupancy": 320,
      "current_pct": 64.0,
      "current_status": "moderate",
      "arrival_rate_per_hour": 15.0,
      "predicted_occupancy": 410,
      "predicted_pct": 82.0,
      "predicted_status": "high",
      "overload_risk": "high",
      "safe_headroom_after": 15
    }
  ]
}
```

---

### `GET /predict/api/<int:shelter_id>`
Returns detailed forecast telemetry for an individual shelter including a time-stepped projection series.

- **Access**: All authenticated users (`@login_required`)
- **URL Parameters**:
  - `shelter_id` *(integer, required)*
- **Query Parameters**:
  - `hours` *(optional, integer, allowed: 1, 3, 6, 12, 24, 48, default: 24)*

#### Response: `200 OK`
```json
{
  "shelter_id": 1,
  "shelter_name": "City Sports Complex",
  "max_capacity": 500,
  "safe_capacity": 425,
  "current_occupancy": 320,
  "arrival_rate_per_hour": 15.0,
  "forecast_hours": 24,
  "predicted_occupancy": 500,
  "predicted_pct": 100.0,
  "overload_risk": "critical",
  "disclaimer": "[ESTIMATE: Projections assume current arrival trends continue. Verify with shelter staff.]",
  "series": [
    {"hour": 0, "time_label": "Now", "projected_occupancy": 320, "projected_pct": 64.0},
    {"hour": 2, "time_label": "+2h", "projected_occupancy": 350, "projected_pct": 70.0},
    {"hour": 4, "time_label": "+4h", "projected_occupancy": 380, "projected_pct": 76.0},
    {"hour": 6, "time_label": "+6h", "projected_occupancy": 410, "projected_pct": 82.0}
  ]
}
```

---

## 5. Alerts Telemetry API

### `GET /alerts/api/active`
Returns real-time active warnings and severity tallies.

- **Access**: All authenticated users (`@login_required`)

#### Response: `200 OK`
```json
{
  "counts": {
    "total": 3,
    "critical": 1,
    "warning": 2,
    "info": 0,
    "unread": 1
  },
  "alerts": [
    {
      "id": 7,
      "shelter_id": 3,
      "shelter_name": "Central High Gym",
      "alert_type": "critical_capacity",
      "severity": "critical",
      "message": "Shelter is at 97% capacity with only 6 safe spots remaining.",
      "is_read": false,
      "created_at": "2026-09-13T09:45:00Z",
      "time_ago": "25 mins ago"
    }
  ]
}
```
