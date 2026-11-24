# Database Design & Schema Documentation

This document describes the relational database design, table schemas, entity relationships, indexes, and locking strategies used in the **Emergency Shelter Capacity Prediction and Redistribution System**.

---

## 1. Entity-Relationship Overview

The database is built on **MySQL 8.x (InnoDB Engine)** using `utf8mb4` character encoding. Foreign keys are strictly defined to enforce referential integrity across all operational workflows.

```
                    ┌──────────────────┐
                    │      users       │
                    └─────────┬────────┘
                              │
         ┌────────────────────┼────────────────────┬────────────────────┐
         │ 1:N (managed_by)   │ 1:N (submitted_by) │ 1:N (recorded_by)  │ 1:N (resolved_by)
         ▼                    ▼                    ▼                    ▼
   ┌──────────┐        ┌──────────────┐     ┌─────────────┐       ┌──────────┐
   │ shelters │        │shelter_reqs  │     │ occ_history │       │  alerts  │
   └─────┬────┘        └──────┬───────┘     └─────────────┘       └──────────┘
         │                    │
         ├──────────┐         │
     1:1 │      1:1 │         │ 1:N
         ▼          ▼         │
   ┌──────────┐┌──────────┐   │
   │facilities││resources │   │
   └──────────┘└──────────┘   │
         │          │         │
         │ 1:N      │ 1:N     │
         └──────────┼─────────┘
                    ▼
             ┌─────────────┐
             │ allocations │
             └─────────────┘
```

---

## 2. Table Specifications

### 2.1 `users` Table
Stores authentication credentials, operational roles, and account statuses.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `full_name` | `VARCHAR(120)` | `NOT NULL` | Full name of the user |
| `email` | `VARCHAR(180)` | `NOT NULL`, `UNIQUE` | User email address (login credential) |
| `password_hash` | `VARCHAR(256)` | `NOT NULL` | Bcrypt hashed password (`$2b$`) |
| `role` | `ENUM(...)` | `NOT NULL`, `DEFAULT 'citizen'` | Allowed: `admin`, `authority`, `responder`, `shelter_manager`, `citizen` |
| `is_active` | `BOOLEAN` | `NOT NULL`, `DEFAULT TRUE` | Whether the user account can sign in |
| `created_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Account creation timestamp |
| `updated_at` | `DATETIME` | `NOT NULL`, `ON UPDATE CURRENT_TIMESTAMP` | Last profile update timestamp |

---

### 2.2 `shelters` Table
Stores physical shelter locations, capacities, coordinates, and operating states.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `name` | `VARCHAR(150)` | `NOT NULL`, `UNIQUE` | Human-readable shelter name |
| `address` | `VARCHAR(300)` | `NOT NULL` | Street address or geographic landmark |
| `latitude` | `DECIMAL(9,6)` | `NOT NULL` | GPS latitude coordinate (-90.0 to 90.0) |
| `longitude` | `DECIMAL(9,6)` | `NOT NULL` | GPS longitude coordinate (-180.0 to 180.0) |
| `max_capacity` | `INT` | `NOT NULL` | Physical maximum head count ceiling |
| `current_occupancy` | `INT` | `NOT NULL`, `DEFAULT 0` | Current real-time occupancy |
| `status` | `ENUM(...)` | `NOT NULL`, `DEFAULT 'active'` | Allowed: `active`, `inactive`, `full`, `damaged`, `closed` |
| `safe_limit_pct` | `INT` | `NULL` | Shelter safe limit override % (uses config if NULL) |
| `managed_by` | `INT` | `FK -> users.id`, `ON DELETE SET NULL` | User ID of the assigned shelter manager |
| `notes` | `TEXT` | `NULL` | Operational notes or special access instructions |
| `created_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Creation timestamp |
| `updated_at` | `DATETIME` | `NOT NULL`, `ON UPDATE CURRENT_TIMESTAMP` | Last updated timestamp |

**Indexes:**
- `idx_shelters_location (latitude, longitude)`: Optimizes proximity filtering queries.
- `idx_shelters_status (status)`: Optimizes queries filtering active shelters.

---

### 2.3 `shelter_facilities` Table
1-to-1 relationship with `shelters`. Tracks 8 physical capabilities and accessibility features.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `shelter_id` | `INT` | `FK -> shelters.id`, `ON DELETE CASCADE`, `UNIQUE` | Shelter foreign key |
| `has_medical_support` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | On-site medical triage / nursing staff |
| `has_food` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Prepared meals or food distribution |
| `has_wheelchair_access` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Wheelchair ramps & accessible bathrooms |
| `has_electricity` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Functional power grid or generator backup |
| `has_toilets` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Sanitary toilet facilities |
| `has_running_water` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Piped municipal water supply |
| `has_kitchen` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Cooking facilities on premises |
| `has_family_area` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Partitioned space for families with children |
| `notes` | `TEXT` | `NULL` | Free-text notes on facility limitations |
| `updated_at` | `DATETIME` | `NOT NULL`, `ON UPDATE CURRENT_TIMESTAMP` | Last update timestamp |
| `updated_by` | `INT` | `FK -> users.id`, `ON DELETE SET NULL` | User who last updated facilities |

---

### 2.4 `resources` Table
1-to-1 relationship with `shelters`. Tracks inventory quantities of essential supplies.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `shelter_id` | `INT` | `FK -> shelters.id`, `ON DELETE CASCADE`, `UNIQUE` | Shelter foreign key |
| `beds_available` | `INT` | `NOT NULL`, `DEFAULT 0` | Available beds / cots |
| `food_portions` | `INT` | `NOT NULL`, `DEFAULT 0` | Meal portions ready for distribution |
| `water_litres` | `INT` | `NOT NULL`, `DEFAULT 0` | Safe potable drinking water (litres) |
| `medicine_kits` | `INT` | `NOT NULL`, `DEFAULT 0` | First-aid & basic medical treatment packs |
| `blankets` | `INT` | `NOT NULL`, `DEFAULT 0` | Blankets / sleeping bags |
| `notes` | `TEXT` | `NULL` | Inventory notes |
| `updated_at` | `DATETIME` | `NOT NULL`, `ON UPDATE CURRENT_TIMESTAMP` | Last stock update timestamp |
| `updated_by` | `INT` | `FK -> users.id`, `ON DELETE SET NULL` | User who last updated inventory |

---

### 2.5 `shelter_requests` Table
Stores evacuation group placement requests submitted by first responders or citizens.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `submitted_by` | `INT` | `FK -> users.id`, `ON DELETE RESTRICT` | Submitting user ID |
| `group_size` | `INT` | `NOT NULL` | Total evacuees in group (> 0) |
| `latitude` | `DECIMAL(9,6)` | `NOT NULL` | Incident location latitude |
| `longitude` | `DECIMAL(9,6)` | `NOT NULL` | Incident location longitude |
| `location_name` | `VARCHAR(200)` | `NULL` | Text landmark or incident location |
| `requesting_team` | `VARCHAR(150)` | `NULL` | Dispatch unit or group name |
| `contact_phone` | `VARCHAR(50)` | `NULL` | Contact phone number |
| `injured_count` | `INT` | `NOT NULL`, `DEFAULT 0` | Number of injured evacuees |
| `elderly_count` | `INT` | `NOT NULL`, `DEFAULT 0` | Number of elderly evacuees |
| `children_count` | `INT` | `NOT NULL`, `DEFAULT 0` | Number of children |
| `accessibility_requirements` | `TEXT` | `NULL` | Wheelchair / mobility requirements |
| `medical_requirements` | `TEXT` | `NULL` | Critical medical care descriptions |
| `other_special_requirements`| `TEXT` | `NULL` | Other requirements (e.g. dietary, infants) |
| `notes` | `TEXT` | `NULL` | General notes |
| `status` | `ENUM(...)` | `NOT NULL`, `DEFAULT 'pending'` | Allowed: `pending`, `allocated`, `partially_allocated`, `cancelled` |
| `submitted_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Request timestamp |
| `updated_at` | `DATETIME` | `NOT NULL`, `ON UPDATE CURRENT_TIMESTAMP` | Last status change timestamp |

---

### 2.6 `allocations` Table
Audit-safe records of confirmed evacuee placements into shelters.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `request_id` | `INT` | `FK -> shelter_requests.id`, `ON DELETE RESTRICT` | Request reference |
| `shelter_id` | `INT` | `FK -> shelters.id`, `ON DELETE RESTRICT` | Placed shelter reference |
| `allocated_count` | `INT` | `NOT NULL` | Number of people placed in this shelter |
| `confirmed` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Whether placement was confirmed |
| `confirmed_at` | `DATETIME` | `NULL` | Exact timestamp when confirmed |
| `confirmed_by` | `INT` | `FK -> users.id`, `ON DELETE SET NULL` | User who confirmed the placement |
| `notes` | `TEXT` | `NULL` | Placement instructions / dispatch notes |

---

### 2.7 `occupancy_history` Table
Append-only historical audit trail. Never updated or mutated in place.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `shelter_id` | `INT` | `FK -> shelters.id`, `ON DELETE CASCADE` | Target shelter reference |
| `occupancy` | `INT` | `NOT NULL` | Occupancy level recorded at this timestamp |
| `recorded_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Change timestamp |
| `recorded_by` | `INT` | `FK -> users.id`, `ON DELETE SET NULL` | Responsible user who made or confirmed the update |

**Index:**
- `idx_history_shelter_time (shelter_id, recorded_at)`: Accelerates time-series queries for prediction engine.

---

### 2.8 `alerts` Table
Stores operational warnings, capacity breaches, and shortages.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `INT` | `PK`, `AUTO_INCREMENT` | Unique identifier |
| `shelter_id` | `INT` | `FK -> shelters.id`, `ON DELETE CASCADE`, `NULL` | Related shelter (if applicable) |
| `alert_type` | `VARCHAR(50)` | `NOT NULL` | `critical_capacity`, `overcrowded`, `predicted_overload`, `resource_shortage`, `shelter_damaged` |
| `severity` | `ENUM(...)` | `NOT NULL` | Allowed: `critical`, `warning`, `info` |
| `message` | `TEXT` | `NOT NULL` | Human-readable explanation |
| `is_read` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Read status |
| `is_resolved` | `BOOLEAN` | `NOT NULL`, `DEFAULT FALSE` | Resolution status |
| `created_at` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Generation timestamp |
| `resolved_at` | `DATETIME` | `NULL` | Resolution timestamp |
| `resolved_by` | `INT` | `FK -> users.id`, `ON DELETE SET NULL` | Resolving user |

---

## 3. Concurrency & Locking Strategy

To ensure zero race conditions during simultaneous group placements:
1. **Sorted Row-Level Locks**:
   ```python
   # Sort IDs to guarantee consistent lock acquisition order across all threads
   sorted_ids = sorted([item['shelter_id'] for item in allocations])
   shelters = (Shelter.query
               .filter(Shelter.id.in_(sorted_ids))
               .with_for_update()  # SELECT ... FOR UPDATE
               .all())
   ```
2. **Why Sorted Order Matters**: If Thread A locks Shelter 1 then Shelter 2, while Thread B locks Shelter 2 then Shelter 1, a database deadlock will occur. By strictly sorting shelter IDs before acquiring locks, deadlocks are mathematically eliminated.
3. **Pessimistic Verification**: Because rows are locked with `with_for_update()`, no other transaction can alter shelter occupancies until the current transaction commits or rolls back. Safe available capacity is re-checked under this lock before any occupancy count is incremented.
