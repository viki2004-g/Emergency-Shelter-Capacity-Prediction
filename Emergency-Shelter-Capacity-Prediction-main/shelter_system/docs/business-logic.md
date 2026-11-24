# Core Business Logic & Algorithmic Design

This document details the mathematical models, formulas, decision trees, and transaction protocols implemented across the service layer of the **Emergency Shelter Capacity Prediction and Redistribution System**.

---

## 1. Capacity & Status Classification Engine

Implemented in [`services/capacity.py`](file:///d:/Cdac%20Project/shelter_system/services/capacity.py).

### 1.1 Mathematical Formulas

1. **Available Physical Capacity:**
   $$\text{Available Capacity} = \text{Max Capacity} - \text{Current Occupancy}$$

2. **Safe Planning Capacity:**
   $$\text{Safe Capacity} = \lfloor \text{Max Capacity} \times \frac{\text{Safe Limit \%}}{100} \rfloor$$
   *Note: Defaults to 85% unless overridden on a per-shelter basis.*

3. **Safe Available Capacity (Headroom):**
   $$\text{Safe Available} = \text{Safe Capacity} - \text{Current Occupancy}$$

4. **Occupancy Percentage:**
   $$\text{Occupancy \%} = \frac{\text{Current Occupancy}}{\text{Max Capacity}} \times 100$$

### 1.2 Capacity Status Classification
Occupancy percentages are classified into 5 operational levels:

```
0% ──────────── 60% ──────────── 80% ──────────── 95% ──────────── 100% ──────────>
    [ SAFE ]         [ MODERATE ]       [ HIGH ]      [ CRITICAL ]   [ OVERCROWDED ]
```

- **`Safe`** ($\le 60.0\%$): Normal operations; plenty of room for incoming evacuees.
- **`Moderate`** ($60.1\% - 80.0\%$): Stable; normal monitoring.
- **`High`** ($80.1\% - 95.0\%$): Approaching safe planning ceiling; preparations for diversion begin.
- **`Critical`** ($95.1\% - 100.0\%$): Safe limit breached; very few emergency spots remain.
- **`Overcrowded`** ($> 100.0\%$): Physical capacity exceeded; dangerous conditions requiring immediate evacuation/redistribution.

---

## 2. Proximity & Multi-Criteria Scoring Engine

Implemented in [`services/scoring.py`](file:///d:/Cdac%20Project/shelter_system/services/scoring.py).

### 2.1 Geographic Distance (Haversine Formula)
Computes great-circle distance in kilometres between two GPS coordinates:

$$\Delta\text{lat} = \text{lat}_2 - \text{lat}_1, \quad \Delta\text{lon} = \text{lon}_2 - \text{lon}_1$$
$$a = \sin^2\left(\frac{\Delta\text{lat}}{2}\right) + \cos(\text{lat}_1) \times \cos(\text{lat}_2) \times \sin^2\left(\frac{\Delta\text{lon}}{2}\right)$$
$$c = 2 \times \text{atan2}\left(\sqrt{a}, \sqrt{1-a}\right)$$
$$\text{Distance (km)} = R \times c \quad (\text{where } R = 6371.0\text{ km})$$

### 2.2 Component Normalization Formulas

Each component is normalized to a score between $0.0$ and $100.0$:

1. **Distance Score ($S_{\text{dist}}$):**
   $$S_{\text{dist}} = \max\left(0, 100 - (\text{Distance km} \times 5)\right)$$
   *(Shelters within 2 km score $\approx 90\text{--}100$; shelters beyond 20 km score $0$.)*

2. **Capacity Headroom Score ($S_{\text{cap}}$):**
   $$S_{\text{cap}} = \min\left(100, \frac{\text{Safe Available Capacity}}{\text{Group Size}} \times 100\right)$$

3. **Facilities Score ($S_{\text{fac}}$):**
   $$S_{\text{fac}} = \frac{\text{Count of Active Facilities}}{8} \times 100$$

4. **Resources Stock Score ($S_{\text{res}}$):**
   Computes stock ratio across beds, food, water, medicine, and blankets relative to group demand:
   $$S_{\text{res}} = \text{Average}\left(\min(100, \text{Stock Ratio}_i \times 100)\right)$$

### 2.3 Total Weighted Score
Configured via `.env` weights summing to $1.0$:
$$\text{Total Score} = (0.25 \times S_{\text{dist}}) + (0.35 \times S_{\text{cap}}) + (0.20 \times S_{\text{fac}}) + (0.20 \times S_{\text{res}})$$

---

## 3. Recommendation Engine

Implemented in [`services/recommendation.py`](file:///d:/Cdac%20Project/shelter_system/services/recommendation.py).

### 3.1 Two-Stage Pipeline

```
Incoming Request (Group Size, Coordinates, Special Requirements)
    │
    ▼
[ Stage 1: Hard Constraint Exclusion ]
    ├─ Is Shelter Status == 'active'?
    │    NO ──> REJECT (Reason: "Shelter is inactive/damaged")
    ├─ Is Safe Available Capacity >= Group Size?
    │    NO ──> REJECT (Reason: "Insufficient safe headroom")
    ├─ If Group Has Injured: Does Shelter Have 'has_medical_support'?
    │    NO ──> REJECT (Reason: "Lacks required medical support")
    └─ If Group Has Disabled: Does Shelter Have 'has_wheelchair_access'?
         NO ──> REJECT (Reason: "Lacks required wheelchair accessibility")
    │
    ▼ (Remaining Eligible Shelters)
[ Stage 2: Weighted Multi-Criteria Ranking ]
    ├─ Compute Total Score for each eligible shelter
    ├─ Sort descending: Score DESC, Distance ASC
    └─ Generate explainable justifications
```

---

## 4. Multi-Shelter Redistribution Engine

Implemented in [`services/redistribution.py`](file:///d:/Cdac%20Project/shelter_system/services/redistribution.py).

When an incoming crowd cannot fit in any single shelter:

### 4.1 Partitioning Algorithm
1. **Candidate Gathering**: Find all active shelters meeting the group's medical and wheelchair needs with `safe_available_capacity > 0`.
2. **Sorting**: Sort candidates by proximity and multi-criteria score.
3. **Greedy Safe Allocation**:
   ```python
   remaining_people = group_size
   allocations = []

   for shelter in sorted_candidates:
       if remaining_people <= 0:
           break
       quota = min(remaining_people, shelter.safe_available_capacity)
       if quota > 0:
           allocations.append({
               'shelter_id': shelter.id,
               'allocated_count': quota,
               'safe_available_after': shelter.safe_available_capacity - quota
           })
           remaining_people -= quota
   ```
4. **Validation**:
   - If `remaining_people == 0`: Plan succeeds (`is_possible = True`).
   - If `remaining_people > 0`: Network is saturated (`is_possible = False`). Calculates:
     $$\text{Deficit} = \text{Group Size} - \text{Total Allocated}$$
5. **Deferred Policy**: The plan is purely a memory simulation. Database tables are NOT mutated.

---

## 5. Transactional Allocation & Row-Level Locking

Implemented in [`services/allocation.py`](file:///d:/Cdac%20Project/shelter_system/services/allocation.py).

When an authorized operator confirms an allocation plan:

### 5.1 Locking Sequence & ACID Guarantees
```python
# 1. Begin database transaction
try:
    # 2. Sort shelter IDs to eliminate deadlock potential
    sorted_ids = sorted([item['shelter_id'] for item in allocations])

    # 3. Acquire exclusive pessimistic row locks
    locked_shelters = (Shelter.query
                       .filter(Shelter.id.in_(sorted_ids))
                       .with_for_update()
                       .all())

    # 4. Re-verify capacity under lock
    for item in allocations:
        shelter = shelter_map[item['shelter_id']]
        if shelter.safe_available_capacity < item['allocated_count']:
            raise InsufficientCapacityError(...)

    # 5. Persist Allocation rows, update occupancy, and record history logs
    for item in allocations:
        shelter.current_occupancy += item['allocated_count']
        db.session.add(OccupancyHistory(...))
        db.session.add(Allocation(...))

    # 6. Mark request as allocated
    req.status = 'allocated'

    # 7. Commit transaction
    db.session.commit()

except Exception as err:
    # Any error triggers immediate, complete rollback
    db.session.rollback()
    raise err
```

---

## 6. Occupancy Prediction Engine

Implemented in [`services/prediction.py`](file:///d:/Cdac%20Project/shelter_system/services/prediction.py).

### 6.1 Hourly Rate of Arrival
Extracts historical entries from `occupancy_history` over a past time window:
$$\text{Rate (people/hour)} = \frac{\text{Occupancy}_{t2} - \text{Occupancy}_{t1}}{\Delta \text{Hours}}$$

- If rate $> 0$: Crowd is accumulating (risk increasing).
- If rate $< 0$: Evacuees are departing (risk decreasing).
- If no history exists: Rate defaults to $0.0$.

### 6.2 Projection Formula & Clamping
$$\text{Raw Projection} = \text{Current Occupancy} + (\text{Rate} \times \text{Hours Ahead})$$
$$\text{Projected Occupancy} = \min(\text{Max Capacity}, \max(0, \text{Raw Projection}))$$

---

## 7. Early Warning Alerts System

Implemented in [`services/alerts.py`](file:///d:/Cdac%20Project/shelter_system/services/alerts.py).

### 7.1 Automated Rule Triggers
1. **`overcrowded` (Critical)**: `current_occupancy > max_capacity`.
2. **`critical_capacity` (Critical)**: `occupancy_pct >= 95.0%`.
3. **`predicted_overload` (Warning/Critical)**: Projected occupancy breaches safe limit within forecast horizon.
4. **`resource_shortage` (Critical/Warning)**: Drinking water $\le 0$ L or food portions $\le 0$.
5. **`shelter_damaged` (Critical)**: Shelter status set to `damaged`.

### 7.2 Strict Deduplication & Auto-Resolution
- **Deduplication**: Active unresolved alerts of the same `(shelter_id, alert_type)` are updated in place rather than creating duplicate rows.
- **Auto-Resolution**: When a shelter's condition returns to normal (e.g., occupancy drops below 85% or drinking water is restocked), existing unresolved alerts for that condition are automatically marked as resolved with `resolved_at = datetime.utcnow()`.
