# System Architecture Documentation

This document describes the architectural design, component layers, request lifecycles, and security mechanisms of the **Emergency Shelter Capacity Prediction and Redistribution System**.

---

## 1. Architectural Overview

The system is designed as a **modular layered MVC (Model-View-Controller) / Service-Oriented Web Application** built on Flask and MySQL. It emphasizes:
1. **Clean Separation of Concerns**: Routing, business logic, and database persistence are strictly isolated.
2. **Explainable Decision Support**: Complex allocation and recommendation logic runs deterministically with explicit human justifications.
3. **Data Integrity & Concurrency Safety**: Core capacity modifications are transactional and protected against race conditions using pessimistic database locks.
4. **Security Hardening**: Enforces least privilege, defense-in-depth session handling, and stack-trace suppression.

---

## 2. Layered Architecture Diagram

```
+-------------------------------------------------------------------------------+
|                            CLIENT / PRESENTATION                              |
|   Web Browser (HTML5, Bootstrap 5, Chart.js, Vanilla JS, Bootstrap Icons)     |
+-------------------------------------------------------------------------------+
                                     │  ▲  HTTP / HTTPS
                                     ▼  │  JSON / HTML
+-------------------------------------------------------------------------------+
|                        FLASK APPLICATION CORE (app.py)                        |
|   - Config Loader (Dev / Prod / Test)                                         |
|   - Security Extensions: Flask-WTF (CSRF), Flask-Login, Flask-Bcrypt          |
|   - Global Error Handlers (400 Bad Request, 403 Forbidden, 404, 500)          |
+-------------------------------------------------------------------------------+
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
+------------------------------------+ +----------------------------------------+
|       MIDDLEWARE & SECURITY        | |       ROUTE CONTROLLERS (routes/)      |
| - Session Authentication           | | - auth_bp: /auth/*                     |
| - CSRF Token Verification          | | - shelters_bp: /shelters/*             |
| - RBAC Role Decorators:            | | - requests_bp: /requests/*             |
|   * @login_required                | | - recommend_bp: /recommend/*           |
|   * @manager_required              | | - predict_bp: /predict/*               |
|   * @responder_required            | | - alerts_bp: /alerts/*                 |
|   * @authority_required            | | - dashboard_bp: /dashboard/*           |
|   * @admin_required                | | - admin_bp: /admin/*                   |
+------------------------------------+ +----------------------------------------+
                                                           │
                                                           ▼
+-------------------------------------------------------------------------------+
|                         BUSINESS SERVICE LAYER (services/)                    |
| - capacity.py:       Occupancy %, safe limits, status categorization          |
| - scoring.py:        Haversine distance, multi-criteria normalization         |
| - recommendation.py: Hard constraint filtering, explainable scoring           |
| - redistribution.py: Safe multi-shelter quota partitioning & deficit analysis |
| - allocation.py:     Transactional row-level locking & atomic execution       |
| - prediction.py:     Rate-of-arrival trend calculation & forecast horizon     |
| - alerts.py:         Rule evaluation, deduplication, auto-resolution          |
| - dashboard.py:      Live aggregation, Chart.js datasets, operational metrics |
+-------------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------------+
|                      DATA PERSISTENCE LAYER (models/)                         |
|   SQLAlchemy 2.0 ORM Models:                                                  |
|   User | Shelter | ShelterFacility | Resource | ShelterRequest | Allocation | |
|   OccupancyHistory | Alert                                                    |
+-------------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------------+
|                        DATABASE ENGINE (MySQL 8.x)                            |
|   - InnoDB Engine (ACID transactions, foreign key constraints, row locks)     |
|   - Character Set: utf8mb4 / utf8mb4_unicode_ci                               |
+-------------------------------------------------------------------------------+
```

---

## 3. Separation of Responsibilities

### 3.1 Route Controllers (`routes/`)
- Responsible **only** for receiving incoming HTTP requests, parsing query parameters/form bodies, invoking the appropriate service functions, and selecting a Jinja2 template or JSON response.
- **Rule:** Routes never implement mathematical scoring algorithms, redistribution partitioning, or direct low-level transactional locking logic.

### 3.2 Service Layer (`services/`)
- Contains pure Python business logic.
- Services can be tested independently of HTTP request contexts.
- Handles complex operations such as:
  - Computing Haversine distances between incident coordinates and shelter locations.
  - Applying multi-criteria weights across distance, capacity, facilities, and resources.
  - Calculating linear arrival rates from historical occupancy logs.
  - Executing atomic multi-shelter allocations with explicit capacity verification under row-level database locks.

### 3.3 Data Layer (`models/`)
- Maps database tables to Python objects via SQLAlchemy.
- Encapsulates entity-level helper methods and read-only calculated properties (e.g., `shelter.available_capacity`, `shelter.safe_capacity`, `shelter.capacity_status`, `user.can_manage_shelters()`).

---

## 4. End-to-End Request Lifecycle

### Example: Confirming a Multi-Shelter Allocation

```
User (Responder)                  Flask Router               Allocation Service              MySQL (InnoDB)
       │                                │                            │                              │
       │ POST /recommend/redistribute/  │                            │                              │
       │      confirm/<req_id>          │                            │                              │
       ├───────────────────────────────>│                            │                              │
       │                                │ 1. Verify CSRF Token       │                              │
       │                                │ 2. Verify Responder Auth   │                              │
       │                                │ 3. Dispatch to controller  │                              │
       │                                ├───────────────────────────>│                              │
       │                                │                            │ 4. Begin Transaction         │
       │                                │                            ├─────────────────────────────>│
       │                                │                            │ 5. SELECT ... FOR UPDATE     │
       │                                │                            │    (Lock shelter rows)       │
       │                                │                            ├─────────────────────────────>│
       │                                │                            │    (Rows locked & returned)  │
       │                                │                            │<─────────────────────────────┤
       │                                │                            │ 6. Re-verify safe capacity   │
       │                                │                            │ 7. Insert Allocation records │
       │                                │                            │ 8. UPDATE shelter occupancy  │
       │                                │                            │ 9. Insert History records    │
       │                                │                            │ 10. UPDATE request status    │
       │                                │                            ├─────────────────────────────>│
       │                                │                            │ 11. COMMIT Transaction       │
       │                                │                            ├─────────────────────────────>│
       │                                │<───────────────────────────┤ (Success returned)           │
       │                                │ 12. Flash Success Message  │                              │
       │<───────────────────────────────┤ 13. HTTP 302 Redirect      │                              │
```

---

## 5. Security & Authorization Architecture

### 5.1 Role-Based Access Control (RBAC)
Access control is implemented via Python decorators in [`utils/decorators.py`](file:///d:/Cdac%20Project/shelter_system/utils/decorators.py):
- `@manager_required`: Grants access to `shelter_manager` and `admin`.
- `@responder_required`: Grants access to `responder` and `admin`.
- `@authority_required`: Grants access to `authority` and `admin`.
- `@admin_required`: Strictly requires `admin`.

### 5.2 Ownership Verification (IDOR Defense)
- **Shelters**: Shelter managers can only modify the specific shelter assigned to their user ID (`shelter.managed_by == current_user.id`). Admins bypass this constraint.
- **Requests**: Citizens can only view or cancel requests they personally created (`req.submitted_by == current_user.id`). Responders and admins can view all requests.

### 5.3 Error Handling & Information Exposure
- **Stack Trace Suppression**: A custom HTTP 500 handler suppresses Python tracebacks and database error messages.
- **Automatic Rollback**: The 500 handler explicitly invokes `db.session.rollback()` so broken database sessions never poison subsequent requests in the connection pool.
- **Generic Safe Feedback**: Controllers catch unhandled system exceptions, log the full traceback server-side via `current_app.logger.exception()`, and display a friendly generic message to end users.
