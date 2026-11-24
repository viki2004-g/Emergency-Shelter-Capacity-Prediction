-- =============================================================================
-- Emergency Shelter Capacity Prediction & Redistribution System
-- MySQL 8.x Schema  — matches SQLAlchemy models exactly
--
-- Use this file to:
--   1. Study the SQL behind the SQLAlchemy models
--   2. Recreate the schema manually if needed
--   3. Review foreign key relationships
--
-- Run order: this entire file top to bottom.
-- MySQL will respect FK order because tables are created dependency-first.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS shelter_system
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE shelter_system;


-- =============================================================================
-- TABLE: users
--
-- Stores all system users.
-- The `role` column controls what each user is allowed to see and do.
-- There are no separate permissions tables — roles are simple ENUM values
-- checked in the application layer (Stage 3).
--
-- Relationships:
--   users.id ← shelters.managed_by       (shelter has one manager)
--   users.id ← occupancy_history.recorded_by
--   users.id ← shelter_requests.submitted_by
--   users.id ← allocations.confirmed_by
--   users.id ← alerts.resolved_by
--   users.id ← resources.updated_by
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id            INT           AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(120)  NOT NULL,
    email         VARCHAR(180)  NOT NULL,
    password_hash VARCHAR(256)  NOT NULL,
    role          ENUM('admin','authority','responder','shelter_manager','citizen')
                  NOT NULL DEFAULT 'citizen',
    is_active     BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                  ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT uq_users_email UNIQUE (email)
) ENGINE=InnoDB;


-- =============================================================================
-- TABLE: shelters
--
-- One row = one physical shelter location.
--
-- latitude / longitude: stored as DECIMAL(9,6) for Haversine calculation.
--   DECIMAL(9,6) allows values like 18.516700 — 6 decimal places gives
--   ~0.1 metre precision, which is more than enough.
--
-- safe_limit_pct: optional per-shelter override for the safe capacity limit.
--   If NULL, the application uses the system default (SAFE_OCCUPANCY_LIMIT_PCT
--   in config / .env). E.g. 85 means "plan for 85% of max_capacity".
--
-- managed_by: references the shelter_manager user responsible for this shelter.
--   ON DELETE SET NULL — if the manager account is deleted, the shelter
--   remains but loses its manager reference (not cascaded/deleted).
-- =============================================================================
CREATE TABLE IF NOT EXISTS shelters (
    id                INT           AUTO_INCREMENT PRIMARY KEY,
    name              VARCHAR(150)  NOT NULL,
    address           VARCHAR(300)  NOT NULL,
    latitude          DECIMAL(9,6)  NOT NULL,
    longitude         DECIMAL(9,6)  NOT NULL,
    max_capacity      INT           NOT NULL,
    current_occupancy INT           NOT NULL DEFAULT 0,
    status            ENUM('active','inactive','full','damaged','closed')
                      NOT NULL DEFAULT 'active',
    safe_limit_pct    INT           NULL,  -- e.g. 85 means plan up to 85% of max_capacity
    managed_by        INT           NULL,
    notes             TEXT          NULL,
    created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                      ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT uq_shelters_name    UNIQUE (name),
    CONSTRAINT fk_shelters_manager FOREIGN KEY (managed_by) REFERENCES users (id)
                                   ON DELETE SET NULL
) ENGINE=InnoDB;

-- Composite index for distance queries (lat/lng range pre-filter)
CREATE INDEX idx_shelters_location ON shelters (latitude, longitude);
-- Status index for dashboard queries ("show all active shelters")
CREATE INDEX idx_shelters_status   ON shelters (status);


-- =============================================================================
-- TABLE: shelter_facilities
--
-- One row per shelter (UNIQUE on shelter_id).
-- Tracks boolean facility flags used by the recommendation engine
-- to filter shelters based on group requirements.
--
-- Example filter: group has wheelchair users → WHERE has_wheelchair_access = TRUE
--
-- Relationship: shelters.id ← shelter_facilities.shelter_id (one-to-one)
-- ON DELETE CASCADE — deleting a shelter removes its facility record.
-- =============================================================================
CREATE TABLE IF NOT EXISTS shelter_facilities (
    id                    INT     AUTO_INCREMENT PRIMARY KEY,
    shelter_id            INT     NOT NULL,
    has_medical_support   BOOLEAN NOT NULL DEFAULT FALSE,
    has_wheelchair_access BOOLEAN NOT NULL DEFAULT FALSE,
    has_electricity       BOOLEAN NOT NULL DEFAULT FALSE,
    has_toilets           BOOLEAN NOT NULL DEFAULT FALSE,
    has_running_water     BOOLEAN NOT NULL DEFAULT FALSE,
    has_kitchen           BOOLEAN NOT NULL DEFAULT FALSE,
    has_family_area       BOOLEAN NOT NULL DEFAULT FALSE,
    notes                 TEXT    NULL,
    updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                          ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT uq_facilities_shelter UNIQUE (shelter_id),
    CONSTRAINT fk_facilities_shelter FOREIGN KEY (shelter_id) REFERENCES shelters (id)
                                     ON DELETE CASCADE
) ENGINE=InnoDB;


-- =============================================================================
-- TABLE: resources
--
-- One row per shelter (UNIQUE on shelter_id).
-- Tracks consumable supply quantities updated by shelter managers.
--
-- These quantities feed into:
--   - Recommendation scoring (Stage 8): resource factor in weighted score
--   - Alert system (Stage 11): low-resource alerts
--
-- updated_by references the user who last updated the record.
-- ON DELETE SET NULL — if the user is deleted, the record remains.
-- =============================================================================
CREATE TABLE IF NOT EXISTS resources (
    id             INT  AUTO_INCREMENT PRIMARY KEY,
    shelter_id     INT  NOT NULL,
    beds_available INT  NOT NULL DEFAULT 0,
    food_portions  INT  NOT NULL DEFAULT 0,
    water_litres   INT  NOT NULL DEFAULT 0,
    medicine_kits  INT  NOT NULL DEFAULT 0,
    blankets       INT  NOT NULL DEFAULT 0,
    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                   ON UPDATE CURRENT_TIMESTAMP,
    updated_by     INT  NULL,

    CONSTRAINT uq_resources_shelter UNIQUE (shelter_id),
    CONSTRAINT fk_resources_shelter FOREIGN KEY (shelter_id) REFERENCES shelters (id)
                                    ON DELETE CASCADE,
    CONSTRAINT fk_resources_user    FOREIGN KEY (updated_by) REFERENCES users (id)
                                    ON DELETE SET NULL
) ENGINE=InnoDB;


-- =============================================================================
-- TABLE: occupancy_history
--
-- Append-only log — records are only INSERTed, never UPDATEd or DELETEd.
-- Every occupancy update produces one new row here.
--
-- Used by:
--   - Prediction engine (Stage 10): calculates arrival rate from this history
--   - Dashboard charts (Stage 11): occupancy trend over time
--
-- The composite index on (shelter_id, recorded_at) is critical:
--   SELECT * FROM occupancy_history
--   WHERE shelter_id = ? ORDER BY recorded_at
--   → uses the index for both filtering and ordering.
-- =============================================================================
CREATE TABLE IF NOT EXISTS occupancy_history (
    id          INT      AUTO_INCREMENT PRIMARY KEY,
    shelter_id  INT      NOT NULL,
    occupancy   INT      NOT NULL,
    recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_by INT      NULL,

    CONSTRAINT fk_history_shelter FOREIGN KEY (shelter_id) REFERENCES shelters (id)
                                  ON DELETE CASCADE,
    CONSTRAINT fk_history_user    FOREIGN KEY (recorded_by) REFERENCES users (id)
                                  ON DELETE SET NULL
) ENGINE=InnoDB;

-- Prediction and chart queries always filter by shelter and order by time
CREATE INDEX idx_history_shelter_time ON occupancy_history (shelter_id, recorded_at);


-- =============================================================================
-- TABLE: shelter_requests
--
-- A request is submitted when a group of displaced people needs shelter.
-- It captures: how many people, where they are, and any special needs.
--
-- Status flow:
--   pending → allocated           (entire group placed in one shelter)
--           → partially_allocated (group split — redistribution used)
--           → cancelled
--
-- submitted_by ON DELETE RESTRICT: prevents deleting a user who has
-- active requests. The request record must be cancelled first.
-- =============================================================================
CREATE TABLE IF NOT EXISTS shelter_requests (
    id                          INT           AUTO_INCREMENT PRIMARY KEY,
    submitted_by                INT           NOT NULL,
    group_size                  INT           NOT NULL,
    latitude                    DECIMAL(9,6)  NOT NULL,
    longitude                   DECIMAL(9,6)  NOT NULL,
    location_name               VARCHAR(200)  NULL,
    requesting_team             VARCHAR(150)  NULL,
    contact_phone               VARCHAR(50)   NULL,
    injured_count               INT           NOT NULL DEFAULT 0,
    elderly_count               INT           NOT NULL DEFAULT 0,
    children_count              INT           NOT NULL DEFAULT 0,
    accessibility_requirements  TEXT          NULL,
    medical_requirements        TEXT          NULL,
    other_special_requirements  TEXT          NULL,
    has_injured                 BOOLEAN       NOT NULL DEFAULT FALSE,
    has_elderly                 BOOLEAN       NOT NULL DEFAULT FALSE,
    has_disabled                BOOLEAN       NOT NULL DEFAULT FALSE,
    has_children                BOOLEAN       NOT NULL DEFAULT FALSE,
    status                      ENUM('pending','allocated','partially_allocated','cancelled')
                                NOT NULL DEFAULT 'pending',
    notes                       TEXT          NULL,
    submitted_at                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_requests_user FOREIGN KEY (submitted_by) REFERENCES users (id)
                                ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE INDEX idx_requests_status    ON shelter_requests (status);
CREATE INDEX idx_requests_submitted ON shelter_requests (submitted_at);


-- =============================================================================
-- TABLE: allocations
--
-- Links a shelter request to one or more shelters.
-- One request → one allocation   (direct recommendation accepted)
-- One request → many allocations (redistribution split)
--
-- confirmed=FALSE: the proposed allocation plan, not yet executed.
-- confirmed=TRUE:  responder confirmed; shelter occupancy has been
--                  updated atomically inside a transaction (Stage 13).
--
-- ON DELETE RESTRICT on request_id and shelter_id: we cannot delete a
-- shelter or request if there are confirmed allocations referencing it.
-- This protects operational data integrity.
-- =============================================================================
CREATE TABLE IF NOT EXISTS allocations (
    id              INT      AUTO_INCREMENT PRIMARY KEY,
    request_id      INT      NOT NULL,
    shelter_id      INT      NOT NULL,
    allocated_count INT      NOT NULL,
    confirmed       BOOLEAN  NOT NULL DEFAULT FALSE,
    confirmed_by    INT      NULL,
    confirmed_at    DATETIME NULL,
    notes           TEXT     NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_alloc_request      FOREIGN KEY (request_id)   REFERENCES shelter_requests (id) ON DELETE RESTRICT,
    CONSTRAINT fk_alloc_shelter      FOREIGN KEY (shelter_id)   REFERENCES shelters (id)         ON DELETE RESTRICT,
    CONSTRAINT fk_alloc_confirmed_by FOREIGN KEY (confirmed_by) REFERENCES users (id)            ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX idx_alloc_request ON allocations (request_id);
CREATE INDEX idx_alloc_shelter ON allocations (shelter_id);
CREATE INDEX idx_alloc_created ON allocations (created_at);


-- =============================================================================
-- TABLE: alerts
--
-- System-generated warnings displayed on the dashboard.
-- Created automatically by services/alerts.py (Stage 11).
--
-- shelter_id is nullable: NULL = system-wide alert, not shelter-specific.
-- ON DELETE CASCADE: deleting a shelter removes its alerts.
--
-- is_resolved: authority or admin marks the alert resolved after action taken.
-- =============================================================================
CREATE TABLE IF NOT EXISTS alerts (
    id          INT  AUTO_INCREMENT PRIMARY KEY,
    shelter_id  INT  NULL,
    alert_type  ENUM('overcrowded','critical_capacity','predicted_overload',
                     'resource_shortage','shelter_damaged')
                NOT NULL,
    severity    ENUM('info','warning','critical') NOT NULL DEFAULT 'warning',
    message     TEXT     NOT NULL,
    is_read     BOOLEAN  NOT NULL DEFAULT FALSE,
    is_resolved BOOLEAN  NOT NULL DEFAULT FALSE,
    resolved_by INT      NULL,
    resolved_at DATETIME NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_alerts_shelter     FOREIGN KEY (shelter_id)  REFERENCES shelters (id) ON DELETE CASCADE,
    CONSTRAINT fk_alerts_resolved_by FOREIGN KEY (resolved_by) REFERENCES users (id)    ON DELETE SET NULL
) ENGINE=InnoDB;

-- Dashboard loads unresolved alerts ordered by date — both columns needed
CREATE INDEX idx_alerts_unresolved ON alerts (is_resolved, created_at);
CREATE INDEX idx_alerts_shelter    ON alerts (shelter_id);


-- =============================================================================
-- RELATIONSHIP SUMMARY (for reference)
--
-- users (1) ──────────── (M) shelters          via shelters.managed_by
-- users (1) ──────────── (M) shelter_requests  via shelter_requests.submitted_by
-- users (1) ──────────── (M) occupancy_history via occupancy_history.recorded_by
-- users (1) ──────────── (M) allocations       via allocations.confirmed_by
-- users (1) ──────────── (M) resources         via resources.updated_by
-- users (1) ──────────── (M) alerts            via alerts.resolved_by
--
-- shelters (1) ───────── (1) shelter_facilities  (one-to-one, unique FK)
-- shelters (1) ───────── (1) resources           (one-to-one, unique FK)
-- shelters (1) ───────── (M) occupancy_history
-- shelters (1) ───────── (M) allocations
-- shelters (1) ───────── (M) alerts
--
-- shelter_requests (1) ─ (M) allocations
-- allocations (M) ─────── (1) shelters
-- =============================================================================
