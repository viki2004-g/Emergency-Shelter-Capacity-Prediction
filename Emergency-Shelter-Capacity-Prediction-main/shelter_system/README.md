# Emergency Shelter Capacity Prediction and Redistribution System

A robust, production-grade decision-support web application built with **Flask** and **MySQL** to assist disaster management teams, emergency operation centers (EOC), and first responders in coordinating emergency shelter logistics during disasters.

> **Operational Principle:** This system is an explainable decision-support tool. It empowers authorized response coordinators with recommendations, predictions, and automated validations, while leaving final placement authority with human operators.

---

## Table of Contents

1. [Project Name](#1-project-name)
2. [Problem Statement](#2-problem-statement)
3. [Solution](#3-solution)
4. [Main Features](#4-main-features)
5. [User Roles](#5-user-roles)
6. [Technology Stack](#6-technology-stack)
7. [Project Architecture](#7-project-architecture)
8. [Database Design](#8-database-design)
9. [Installation](#9-installation)
10. [MySQL Setup](#10-mysql-setup)
11. [Environment Variables](#11-environment-variables)
12. [Running Flask](#12-running-flask)
13. [Test Instructions](#13-test-instructions)
14. [API Endpoints](#14-api-endpoints)
15. [Recommendation Logic](#15-recommendation-logic)
16. [Prediction Logic](#16-prediction-logic)
17. [Redistribution Logic](#17-redistribution-logic)
18. [Transaction & Concurrency Handling](#18-transaction--concurrency-handling)
19. [Screenshots Placeholder](#19-screenshots-placeholder)
20. [Future Improvements](#20-future-improvements)

---

## 1. Project Name

**Emergency Shelter Capacity Prediction and Redistribution System**  
*(Short Name: Shelter Management & Redistribution System)*

---

## 2. Problem Statement

During major emergencies (floods, cyclones, earthquakes, industrial fires, and urban disasters):
- **Uncoordinated Placement:** First responders lack centralized, real-time situational awareness of shelter capacities.
- **Dangerous Overcrowding:** Responders frequently dispatch evacuees to the nearest known shelter without realizing it is already nearing or beyond maximum capacity, resulting in severe resource shortages and secondary safety hazards.
- **Mismatched Special Needs:** Vulnerable evacuees (injured people needing triage, elderly individuals, children, wheelchair users) are often sent to facilities lacking medical staff, ramp access, or adequate drinking water.
- **Single-Shelter Overflow:** When a large group (e.g., 100+ evacuees) arrives, operators struggle to calculate how to split the group across multiple nearby shelters without exceeding individual safe limits.
- **Concurrency Hazards:** Without database-level transactional locking, multiple field response teams can accidentally allocate evacuees to the same shelter at the exact same moment, causing race conditions and severe over-allocation.

---

## 3. Solution

The **Emergency Shelter Capacity Prediction and Redistribution System** solves these challenges by providing:
- **Centralized Network Intelligence:** Real-time visibility into shelter capacities, safe planning thresholds, facility flags, and stock levels across the entire region.
- **Explainable Multi-Criteria Recommendation:** Automated ranking of shelters based on geographic proximity (Haversine formula), available headroom, matching facilities (medical, wheelchair, kitchen), and critical resources.
- **Safe Multi-Shelter Redistribution Engine:** An algorithm that splits large groups across candidate shelters safely, ensuring no shelter breaches its safe operating ceiling.
- **Pessimistic Row-Level Locking:** Strict MySQL transactions (`SELECT ... FOR UPDATE`) that guarantee atomic capacity checks and updates, making simultaneous over-allocation physically impossible.
- **Predictive Overload Forecasting:** Real-time trend estimation calculating arrival rates from historical logs and forecasting capacity 1 to 72 hours ahead with explicit estimation disclaimers.
- **Role-Aware Emergency Dashboard & Alerts:** High-density situational awareness displaying live capacity stats, critical warnings, and automated alert resolution.

---

## 4. Main Features

- **Real-Time Capacity & Occupancy Tracking:** Automatically computes available capacity, safe capacity (configurable, default 85%), occupancy percentage, and dynamic statuses: `Safe`, `Moderate`, `High`, `Critical`, and `Overcrowded`.
- **Facility & Resource Management:** Tracks 8 critical facility flags (*medical support, food meals, wheelchair access, electricity, toilets, running water, kitchen, family area*) and 5 vital inventory counts (*beds, food portions, water litres, medicine kits, blankets*).
- **Group Evacuee Request Intake:** Intake portal for dispatch units and citizens capturing group sizes, incident GPS coordinates, and demographic breakdowns (*injured, elderly, children, accessibility requirements*).
- **Transparent Recommendation Engine:** Multi-criteria scoring with transparent positive reasons and auditable exclusion criteria for rejected shelters.
- **Multi-Shelter Group Redistribution:** Splits incoming crowds across candidate shelters with zero mutations until human operators explicitly confirm the plan.
- **Transactional Atomic Placement:** Prevents race conditions using row-level locking, updates shelter occupancies, records audit history logs, and guarantees automatic rollback on failure.
- **Trend-Based Occupancy Prediction:** Linear arrival rate estimation with bounds clamping and operational estimation notices.
- **Automated Early Warning Alerts:** Detects critical headroom breaches, overcrowding, predicted overloads, and water/medical shortages with strict deduplication and auto-resolution.
- **Role-Aware Incident Command Dashboard:** Clean dashboard featuring real MySQL data, Chart.js telemetry, and actionable quick-filters.
- **Security & Data Hardening:** Bcrypt password hashing with CPU DoS protection, secure session cookies (HttpOnly, SameSite Lax, Secure in production), session fixation defense, CSRF protection via Flask-WTF, and custom error pages (400, 403, 404, 500) suppressing stack traces.

---

## 5. User Roles

The system enforces strict Role-Based Access Control (RBAC):

| Role | Operational Scope & Permissions |
|---|---|
| **`admin`** | Full system administrator. Can create and edit all shelters, manage users, reconfigure global planning limits, and access the admin console. |
| **`authority`** | Emergency Operations Center (EOC) directors. Strategic situational oversight, reviewing and resolving emergency alerts, and inspecting network-wide prediction telemetry. |
| **`responder`** | Field evacuation teams and triage dispatchers. Submits emergency group requests, evaluates recommendation candidate shelters, generates redistribution plans, and confirms placements. |
| **`shelter_manager`** | On-site shelter directors. Can edit facilities, update resource stock, and record live occupancy changes for their assigned shelter. Cannot edit other shelters. |
| **`citizen`** | Public self-service users. Can submit emergency assistance requests for their own family/group and track status updates for their own submissions. |

---

## 6. Technology Stack

- **Backend Framework:** Python 3.12, Flask 3.1.3
- **Database Engine:** MySQL 8.x / MariaDB (InnoDB storage engine)
- **Database ORM & Driver:** SQLAlchemy 2.0, Flask-SQLAlchemy 3.1, PyMySQL 1.2
- **Authentication & Security:** Flask-Login 0.6.3, Flask-Bcrypt 1.0.1, Flask-WTF 1.3.0 (CSRF protection)
- **Configuration & Environment:** python-dotenv 1.2.3
- **Frontend Architecture:** HTML5, Vanilla CSS / Bootstrap 5, Bootstrap Icons, Chart.js (CDN)
- **Testing Framework:** Python Standard Library `unittest`

---

## 7. Project Architecture

The application adopts a clean, layered architecture ensuring strict separation between HTTP handling, business domain logic, and data persistence:

```
d:\Cdac Project\shelter_system/
├── app.py                      # Flask Application Factory & blueprint registration
├── config.py                   # Environment configuration (Dev, Prod, Test)
├── extensions.py               # Shared extensions (db, login_manager, bcrypt, csrf)
├── db_init.py                  # Database initialization and automated seeder
├── requirements.txt            # Python dependencies
├── .env.example                # Configuration template
├── .gitignore                  # Git exclusion rules
│
├── models/                     # SQLAlchemy ORM Data Layer
│   ├── __init__.py
│   ├── user.py                 # User model & password hashing
│   ├── shelter.py              # Shelter entity & capacity calculations
│   ├── facility.py             # ShelterFacility (1-to-1 flags)
│   ├── resource.py             # Resource inventory (1-to-1 quantities)
│   ├── request.py              # ShelterRequest & demographic needs
│   ├── allocation.py           # Confirmed placement records
│   ├── history.py              # Append-only occupancy audit trail
│   └── alert.py                # Operational alerts & severity levels
│
├── routes/                     # Presentation & Controller Layer (Blueprints)
│   ├── auth.py                 # Authentication, registration, secure logout
│   ├── main.py                 # Public landing portal
│   ├── dashboard.py            # Incident command dashboard & telemetry API
│   ├── shelters.py             # Shelter management, occupancy, resources
│   ├── requests.py             # Group shelter requests & status transitions
│   ├── recommend.py            # Recommendation & redistribution engine
│   ├── predict.py              # Prediction forecast views & series API
│   ├── alerts.py               # Alert listing, manual scan, resolution
│   └── admin.py                # Administrator management console
│
├── services/                   # Pure Domain & Business Logic Layer
│   ├── capacity.py             # Capacity formulas & status classification
│   ├── scoring.py              # Haversine distance & multi-criteria scoring
│   ├── recommendation.py       # Candidate filtering & explainable evaluation
│   ├── redistribution.py       # Multi-shelter partitioning algorithm
│   ├── allocation.py           # Pessimistic locking & atomic transactions
│   ├── prediction.py           # Rate of arrival calculation & forecasting
│   ├── alerts.py               # Alert rules, deduplication, auto-resolution
│   └── dashboard.py            # Live aggregation & Chart.js formatting
│
├── templates/                  # Jinja2 HTML5 Templates
│   ├── base.html               # Master layout shell & responsive navigation
│   ├── auth/                   # Login & registration views
│   ├── dashboard/              # EOC dashboard interface
│   ├── shelters/               # Lists, forms, detail cards, occupancy
│   ├── requests/               # Request forms, list, detailed view
│   ├── recommend/              # Scoring evaluation & redistribution plans
│   ├── predict/                # Prediction dashboard & shelter forecast
│   ├── alerts/                 # Alerts console & resolution modal
│   ├── admin/                  # Admin dashboard
│   └── errors/                 # Error pages (400, 403, 404, 500)
│
├── static/                     # Static assets
│   ├── css/style.css           # Clean, restrained emergency design system
│   └── js/main.js              # Client-side validation & utilities
│
├── database/                   # Raw SQL schemas and seeds
│   ├── schema.sql              # Clean DDL matching SQLAlchemy models
│   └── seed_data.sql           # Realistic demonstration dataset
│
├── tests/                      # Automated Test Suites
│   ├── test_system_verification.py # 95-test end-to-end verification
│   ├── test_security.py        # 39-test security audit suite
│   ├── test_allocation_transaction.py
│   ├── test_redistribution.py
│   ├── test_recommendation.py
│   ├── test_prediction.py
│   ├── test_dashboard.py
│   ├── test_alerts.py
│   ├── test_shelters.py
│   ├── test_requests.py
│   ├── test_facilities_resources.py
│   ├── test_occupancy_tracking.py
│   └── test_distance.py
│
└── docs/                       # Detailed Architecture & Technical Docs
    ├── architecture.md         # Layer diagrams & request lifecycles
    ├── database.md             # Schema dictionary, indexes & ER diagrams
    ├── api.md                  # REST JSON endpoint documentation
    └── business-logic.md       # Formulas, algorithms, and locking rules
```

---

## 8. Database Design

The database schema utilizes 8 normalized tables linked by foreign keys with explicit cascade and nullification rules:

```
users (id)
  │
  ├──< shelters (managed_by) ──1:1── shelter_facilities (shelter_id)
  │      │                   └──1:1── resources (shelter_id)
  │      │
  │      ├──< occupancy_history (shelter_id)
  │      ├──< allocations (shelter_id)
  │      └──< alerts (shelter_id)
  │
  ├──< shelter_requests (submitted_by)
  │      │
  │      └──< allocations (request_id)
  │
  ├──< occupancy_history (recorded_by)
  ├──< allocations (confirmed_by)
  └──< alerts (resolved_by)
```

### Table Summary:
1. **`users`**: User identities, roles (`admin`, `authority`, `responder`, `shelter_manager`, `citizen`), and bcrypt password hashes.
2. **`shelters`**: Geographic coordinates (`DECIMAL(9,6)`), capacity limits, current occupancy, operational status, and assigned manager.
3. **`shelter_facilities`**: 1-to-1 table tracking 8 boolean amenity flags (*medical, food, wheelchair, electricity, toilets, running water, kitchen, family area*).
4. **`resources`**: 1-to-1 table tracking inventory levels (*beds, food portions, water, medicine kits, blankets*).
5. **`shelter_requests`**: Evacuee group displacement requests including location, total count, and special needs (*injured, elderly, children, accessibility*).
6. **`allocations`**: Records linking an evacuee request to specific shelters, tracking how many people were placed and confirmation timestamps.
7. **`occupancy_history`**: Append-only log recording every occupancy change, delta, timestamp, and the user responsible.
8. **`alerts`**: Operational early warnings with severities (`critical`, `warning`, `info`) and resolution audit trails.

---

## 9. Installation

### Prerequisites:
- Python 3.11 or 3.12 installed
- MySQL Server 8.0+ or MariaDB 10.5+ running locally or remotely
- Git

### Step-by-Step Setup:

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd shelter_system
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

---

## 10. MySQL Setup

1. **Start your MySQL server** (e.g., via MySQL Workbench, XAMPP, or command line).

2. **Create the database:**
   ```sql
   CREATE DATABASE shelter_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

3. **Initialize the schema and seed data:**
   You can seed the database automatically using the provided Python initializer:
   ```bash
   python db_init.py
   ```
   *Alternatively, import the raw SQL files:*
   ```bash
   mysql -u root -p shelter_system < database/schema.sql
   mysql -u root -p shelter_system < database/seed_data.sql
   ```

---

## 11. Environment Variables

Copy the provided `.env.example` file to `.env`:
```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Configure your local credentials in `.env`:
```ini
# Flask Core
FLASK_APP=app.py
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=change-this-to-a-secure-random-secret-key

# Database Connection
DB_HOST=localhost
DB_PORT=3306
DB_NAME=shelter_system
DB_USER=root
DB_PASSWORD=your_mysql_password_here

# Planning & Capacity Limits
SAFE_OCCUPANCY_LIMIT_PCT=85

# Recommendation Scoring Weights (Must sum to 1.0)
WEIGHT_DISTANCE=0.25
WEIGHT_CAPACITY=0.35
WEIGHT_FACILITIES=0.20
WEIGHT_RESOURCES=0.20

# Prediction Horizon
PREDICT_HOURS_AHEAD=6

# CSRF Protection (Set to True in production)
WTF_CSRF_ENABLED=False
```

---

## 12. Running Flask

Launch the development server:
```bash
python app.py
```
*Or using the Flask CLI:*
```bash
flask run --port=5000
```

Open your browser and navigate to:
```
http://127.0.0.1:5000
```

### Pre-configured Demonstration Accounts
All demo users are initialized with password: **`Password@123`**

| Email | Role | Recommended Use Case |
|---|---|---|
| `admin@shelter.gov` | `admin` | Full system access, shelter CRUD, configuration |
| `authority@shelter.gov` | `authority` | Emergency management dashboard, resolving alerts |
| `responder1@shelter.gov` | `responder` | Submitting requests, running recommendation & redistribution |
| `manager1@shelter.gov` | `shelter_manager` | Updating live occupancy, facilities, and resources |
| `citizen@example.com` | `citizen` | Public portal view, tracking own evacuation requests |

---

## 13. Test Instructions

The system is tested using Python's standard `unittest` framework with automated database rollback and cleanup fixtures.

### Run Comprehensive System Verification (95 Tests):
```bash
python tests/test_system_verification.py
```
*Verifies Authentication, Shelter CRUD, Capacity Logic, Requests, Recommendation, Prediction, Redistribution, and Database Concurrency.*

### Run Security Audit Verification (39 Tests):
```bash
python tests/test_security.py
```
*Verifies Open Redirects, Bcrypt CPU DoS boundaries, Session Fixation, RBAC, IDOR, Error Handler suppression, and CSRF token coverage.*

### Run All Unit Test Suites:
```bash
python -c "import subprocess, sys; files = ['test_alerts.py', 'test_allocation_transaction.py', 'test_dashboard.py', 'test_facilities_resources.py', 'test_occupancy_tracking.py', 'test_prediction.py', 'test_recommendation.py', 'test_redistribution.py', 'test_requests.py', 'test_shelters.py']; [print(f'Running {f}') or subprocess.run([sys.executable, f'tests/{f}'], check=True) for f in files]; print('All suites passed successfully!')"
```

---

## 14. API Endpoints

All JSON API endpoints return structured payloads suitable for headless integration or mobile clients:

| Method | Endpoint | Access Level | Description |
|---|---|---|---|
| `GET` | `/dashboard/api/stats?hours=6` | Login Required | Real-time EOC statistics, alert tallies, and Chart.js datasets |
| `GET` | `/recommend/api/request/<id>` | Responder / Admin | Evaluated candidate rankings, composite scores, and exclusion reasons |
| `GET` | `/recommend/api/redistribute/<id>?hours=6` | Responder / Admin | Multi-shelter partitioning plan, quota breakdown, and remaining capacity |
| `GET` | `/predict/api/all?hours=6` | Login Required | Network-wide forecasted occupancies and overload risk levels |
| `GET` | `/predict/api/<shelter_id>?hours=24` | Login Required | Individual shelter forecast series with time-stepped projection points |
| `GET` | `/alerts/api/active` | Login Required | Unresolved alerts, unread counts, and breakdown by severity |

---

## 15. Recommendation Logic

The recommendation engine follows a two-stage pipeline:

```
All Shelters
    │
    ▼
[Phase 1: Hard Constraint Filter]
  ├─ Operational Status (must be 'active')
  ├─ Safe Available Capacity (must have headroom > 0)
  ├─ Medical Requirement (if group has injured, shelter must have medical support)
  └─ Accessibility Requirement (if group has disabled, shelter must have wheelchair access)
    │
    ├─ Unsuitable Shelters ──> Documented with transparent exclusion reasons
    │
    ▼
[Phase 2: Weighted Multi-Criteria Scoring] (Eligible Candidates)
  ├─ Proximity Score (25%):   Haversine distance (closest = highest score)
  ├─ Headroom Score (35%):    Safe available capacity ratio
  ├─ Facilities Score (20%):  Count of active facility amenities (out of 8)
  └─ Resources Score (20%):   Stock sufficiency across beds, food, water, medicine, blankets
    │
    ▼
Ranked Candidate Shelters with Explainable Justifications
```

---

## 16. Prediction Logic

The prediction engine forecasts near-future occupancy trends based on historical rates of arrival:

1. **Rate of Arrival Calculation:**  
   Inspects the latest and earliest occupancy history entries recorded over a historical window:
   $$\text{Arrival Rate (people/hr)} = \frac{\text{Latest Occupancy} - \text{Earliest Occupancy}}{\text{Hours Elapsed}}$$

2. **Forecast Projection:**  
   $$\text{Projected Occupancy} = \text{Current Occupancy} + (\text{Arrival Rate} \times \text{Forecast Horizon Hours})$$

3. **Safety Clamping:**  
   Projected occupancy is clamped between $0$ and `max_capacity`.

4. **Risk Classification:**  
   - Safe ($< 60\%$)
   - Moderate ($60\% - 80\%$)
   - High ($81\% - 95\%$)
   - Critical ($96\% - 100\%$)
   - Overcrowded ($> 100\%$)

5. **Estimation Notice:**  
   Every prediction screen and API payload clearly displays:  
   `[ESTIMATE: Projections assume current arrival trends remain constant. Verify with on-site staff.]`

---

## 17. Redistribution Logic

When an incoming group cannot fit into a single shelter, the redistribution engine partitions the crowd:

1. Identifies all eligible active shelters that meet the group's medical and accessibility requirements.
2. Calculates each shelter's **safe available capacity**:
   $$\text{Safe Available} = (\text{Max Capacity} \times \text{Safe Limit \%}) - \text{Current Occupancy}$$
3. Ranks candidates by proximity and multi-criteria score.
4. Iteratively fills candidate shelters up to their safe available headroom.
5. Verifies:
   $$\sum \text{Allocated Counts} = \text{Requested Group Size}$$
6. **Deficit Handling:** If total network safe capacity is less than the group size, the plan reports `is_possible = False` and outputs the exact unallocated evacuee deficit.
7. **Deferred Mutation:** No shelter occupancy or database records are altered until an authorized responder clicks **Confirm & Execute Allocation**.

---

## 18. Transaction & Concurrency Handling

To prevent two dispatchers from allocating evacuees to the same shelter at the same time, the system uses **pessimistic row-level locking**:

```
Client 1 (Dispatch A)             Client 2 (Dispatch B)
      │                                 │
1. BEGIN TRANSACTION              1. BEGIN TRANSACTION
      │                                 │
2. SELECT ... FOR UPDATE          2. SELECT ... FOR UPDATE
   (Locks Shelter Row 1)             (WAIT: Row 1 is locked by Client 1)
      │                                 ┆
3. Re-verify Safe Headroom              ┆
   (Capacity is sufficient)             ┆
      │                                 ┆
4. Update Occupancy (+30)               ┆
5. Create Allocation Record             ┆
6. Append History Record                ┆
7. COMMIT TRANSACTION                   ┆
   (Lock on Row 1 released)             ▼
      │                           3. Lock acquired by Client 2
                                  4. Re-verify Safe Headroom
                                     (Now insufficient!)
                                  5. ROLLBACK TRANSACTION
                                     (Returns friendly capacity error)
```

- **Deadlock Prevention:** Shelter IDs are always locked in ascending numerical order (`sorted_ids = sorted(shelter_ids)`).
- **Atomic Rollback:** If capacity is exceeded or any step fails, `db.session.rollback()` is immediately triggered, leaving zero partial updates or orphaned records.

---

## 19. Screenshots Placeholder

*(Place system user interface captures in the `docs/screenshots/` folder)*

```
+-------------------------------------------------------------------------+
| [Screenshot Placeholder: Main Emergency Management Dashboard]           |
| High-density situational awareness, Chart.js load telemetry, alerts   |
+-------------------------------------------------------------------------+

+-------------------------------------------------------------------------+
| [Screenshot Placeholder: Explainable Shelter Recommendation Engine]     |
| Multi-criteria candidate evaluation, scoring breakdown, rejection log  |
+-------------------------------------------------------------------------+

+-------------------------------------------------------------------------+
| [Screenshot Placeholder: Multi-Shelter Group Redistribution Plan]       |
| Multi-shelter partitioning, quota allocation, safe capacity headroom    |
+-------------------------------------------------------------------------+

+-------------------------------------------------------------------------+
| [Screenshot Placeholder: Early Warning Alerts Console]                  |
| Critical overload alerts, shortage notices, modal resolution audit trail|
+-------------------------------------------------------------------------+
```

---

## 20. Future Improvements

1. **Interactive GIS Map Interface:** Integration with OpenStreetMap / Leaflet to display live shelter clusters, evacuation route hazards, and real-time incident perimeters.
2. **Automated SMS / WhatsApp Notification Dispatch:** Direct mobile dispatch messages to field coordinators and shelter managers upon confirmed allocations.
3. **External Sensor & Weather Feeds:** Integration with meteorological APIs (rainfall, flood gauge telemetry) to automatically trigger proactive pre-evacuation recommendations.
4. **Offline PWA Support:** Service-worker caching allowing field responders in connectivity-denied disaster zones to record evacuees locally and sync when connections recover.
