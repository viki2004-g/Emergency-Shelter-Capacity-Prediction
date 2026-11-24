-- =============================================================================
-- Emergency Shelter Capacity Prediction & Redistribution System
-- Seed Data — Realistic sample for development and testing
-- Run AFTER schema.sql
-- =============================================================================

USE shelter_system;

-- =============================================================================
-- USERS
-- Passwords are bcrypt hashes of 'Password@123' (for ALL seed users).
-- In production, each user sets their own password.
-- Hash generated with: bcrypt.generate_password_hash('Password@123', rounds=12)
-- =============================================================================
INSERT INTO users (full_name, email, password_hash, role) VALUES
  ('System Administrator',  'admin@shelter.gov',    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'admin'),
  ('District Authority',    'authority@shelter.gov', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'authority'),
  ('Rahul Sharma',          'responder1@shelter.gov','$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'responder'),
  ('Priya Nair',            'responder2@shelter.gov','$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'responder'),
  ('Amit Kulkarni',         'manager1@shelter.gov',  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'shelter_manager'),
  ('Sunita Desai',          'manager2@shelter.gov',  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'shelter_manager'),
  ('Vikram Patel',          'manager3@shelter.gov',  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'shelter_manager'),
  ('Meena Joshi',           'manager4@shelter.gov',  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'shelter_manager'),
  ('Citizen User',          'citizen@example.com',   '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TsuMeZnQpLbrK0vBxFZ6SZJatXYm', 'citizen');

-- =============================================================================
-- SHELTERS
-- Based around Pune, Maharashtra as a realistic disaster scenario area.
-- lat/lng are real coordinates of public venues in Pune.
-- =============================================================================
INSERT INTO shelters (name, address, latitude, longitude, max_capacity, current_occupancy, status, managed_by, notes) VALUES
  ('Deccan Gymkhana Relief Centre',
   'Deccan Gymkhana, Pune 411004',
   18.5167, 73.8389, 500, 312, 'active', 5,
   'Primary flood relief centre for west Pune. Ground floor accessible.'),

  ('Shivajinagar Community Hall',
   'FC Road, Shivajinagar, Pune 411005',
   18.5308, 73.8474, 300, 278, 'active', 6,
   'Near bus terminus. Good access for rescue vehicles.'),

  ('Hadapsar Sports Complex',
   'Hadapsar, Pune 411028',
   18.5018, 73.9252, 600, 130, 'active', 7,
   'Largest shelter in east Pune. Open area available for overflow tents.'),

  ('Kothrud School Emergency Shelter',
   'Kothrud, Pune 411038',
   18.5074, 73.8077, 400, 380, 'active', 8,
   'School premises. Separate rooms available for families and medical cases.'),

  ('Baner Relief Camp',
   'Baner Road, Pune 411045',
   18.5600, 73.7855, 250, 60, 'active', 5,
   'Newer facility. Fully equipped kitchen and medical bay.'),

  ('Kondhwa Temporary Shelter',
   'Kondhwa Budruk, Pune 411048',
   18.4686, 73.8808, 350, 320, 'active', 6,
   'Approaching capacity. Monitor closely.'),

  ('PCMC Pimpri Relief Centre',
   'Pimpri-Chinchwad, Pune 411018',
   18.6298, 73.7997, 450, 90, 'active', 7,
   'Industrial area shelter. Suitable for large group redistribution.'),

  ('Wagholi Rural Shelter',
   'Wagholi, Pune 412207',
   18.5697, 73.9826, 200, 195, 'active', 8,
   'Near capacity. Limited medical facilities.');

-- =============================================================================
-- SHELTER FACILITIES
-- One row per shelter
-- =============================================================================
INSERT INTO shelter_facilities
  (shelter_id, has_medical_support, has_wheelchair_access, has_electricity,
   has_toilets, has_running_water, has_kitchen, has_family_area) VALUES
  (1, TRUE,  TRUE,  TRUE,  TRUE,  TRUE,  TRUE,  TRUE),   -- Deccan Gymkhana
  (2, FALSE, FALSE, TRUE,  TRUE,  TRUE,  FALSE, FALSE),   -- Shivajinagar
  (3, TRUE,  TRUE,  TRUE,  TRUE,  TRUE,  TRUE,  TRUE),   -- Hadapsar Sports
  (4, TRUE,  FALSE, TRUE,  TRUE,  TRUE,  TRUE,  TRUE),   -- Kothrud School
  (5, TRUE,  TRUE,  TRUE,  TRUE,  TRUE,  TRUE,  FALSE),  -- Baner
  (6, FALSE, FALSE, TRUE,  TRUE,  TRUE,  FALSE, FALSE),   -- Kondhwa
  (7, FALSE, TRUE,  TRUE,  TRUE,  TRUE,  TRUE,  FALSE),   -- PCMC Pimpri
  (8, FALSE, FALSE, FALSE, TRUE,  FALSE, FALSE, FALSE);   -- Wagholi (limited)

-- =============================================================================
-- RESOURCES
-- Updated by shelter managers; quantities reflect current stock
-- =============================================================================
INSERT INTO resources
  (shelter_id, beds_available, food_portions, water_litres, medicine_kits, blankets) VALUES
  (1, 420, 600,  2000, 30, 450),  -- Deccan Gymkhana
  (2, 280,  300,  900,  5, 260),  -- Shivajinagar (low medicine)
  (3, 580, 800,  3000, 40, 580),  -- Hadapsar Sports
  (4, 380,  400, 1200, 25, 390),  -- Kothrud School
  (5, 230,  300, 1000, 20, 240),  -- Baner
  (6, 330,  350,  800,  3, 310),  -- Kondhwa (low medicine)
  (7, 440,  550, 1800, 15, 420),  -- PCMC Pimpri
  (8, 180,  200,  300,  2, 160);  -- Wagholi (very limited resources)

-- =============================================================================
-- OCCUPANCY HISTORY
-- Historical snapshots over the past 48 hours for the prediction engine.
-- These represent realistic disaster scenario arrival patterns.
-- =============================================================================
INSERT INTO occupancy_history (shelter_id, occupancy, recorded_at) VALUES
  -- Shelter 1: Deccan Gymkhana — steady arrivals
  (1, 120, DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (1, 180, DATE_SUB(NOW(), INTERVAL 42 HOUR)),
  (1, 220, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (1, 260, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (1, 290, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (1, 312, DATE_SUB(NOW(), INTERVAL  2 HOUR)),

  -- Shelter 2: Shivajinagar — rapid fill
  (2, 50,  DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (2, 120, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (2, 200, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (2, 250, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (2, 270, DATE_SUB(NOW(), INTERVAL  6 HOUR)),
  (2, 278, DATE_SUB(NOW(), INTERVAL  1 HOUR)),

  -- Shelter 3: Hadapsar — low usage
  (3,  20, DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (3,  50, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (3,  80, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (3, 110, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (3, 125, DATE_SUB(NOW(), INTERVAL  3 HOUR)),
  (3, 130, DATE_SUB(NOW(), INTERVAL  1 HOUR)),

  -- Shelter 4: Kothrud — near critical
  (4, 200, DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (4, 280, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (4, 330, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (4, 360, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (4, 375, DATE_SUB(NOW(), INTERVAL  4 HOUR)),
  (4, 380, DATE_SUB(NOW(), INTERVAL  1 HOUR)),

  -- Shelter 5: Baner — light use
  (5,  10, DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (5,  20, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (5,  35, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (5,  50, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (5,  58, DATE_SUB(NOW(), INTERVAL  2 HOUR)),
  (5,  60, DATE_SUB(NOW(), INTERVAL  1 HOUR)),

  -- Shelter 6: Kondhwa — approaching capacity fast
  (6, 100, DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (6, 180, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (6, 240, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (6, 290, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (6, 310, DATE_SUB(NOW(), INTERVAL  4 HOUR)),
  (6, 320, DATE_SUB(NOW(), INTERVAL  1 HOUR)),

  -- Shelter 7: PCMC Pimpri — slow fill
  (7,  20, DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (7,  40, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (7,  60, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (7,  75, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (7,  88, DATE_SUB(NOW(), INTERVAL  3 HOUR)),
  (7,  90, DATE_SUB(NOW(), INTERVAL  1 HOUR)),

  -- Shelter 8: Wagholi — near capacity
  (8,  80, DATE_SUB(NOW(), INTERVAL 48 HOUR)),
  (8, 120, DATE_SUB(NOW(), INTERVAL 36 HOUR)),
  (8, 155, DATE_SUB(NOW(), INTERVAL 24 HOUR)),
  (8, 175, DATE_SUB(NOW(), INTERVAL 12 HOUR)),
  (8, 190, DATE_SUB(NOW(), INTERVAL  4 HOUR)),
  (8, 195, DATE_SUB(NOW(), INTERVAL  1 HOUR));

-- =============================================================================
-- SHELTER REQUESTS (sample pending requests)
-- =============================================================================
INSERT INTO shelter_requests
  (submitted_by, group_size, latitude, longitude, location_name,
   has_injured, has_elderly, has_disabled, has_children, status, notes)
VALUES
  -- Responder 1 submits a group of 150 from flood-hit Sinhagad area
  (3, 150, 18.3667, 73.7555, 'Sinhagad Road, Pune',
   TRUE, TRUE, FALSE, TRUE, 'pending',
   'Flood evacuation. 5 injured, 15 elderly, 30 children. Need medical priority.'),

  -- Responder 2 submits a smaller group from Katraj
  (4, 45, 18.4530, 73.8650, 'Katraj, Pune',
   FALSE, TRUE, TRUE, FALSE, 'pending',
   '8 elderly, 4 wheelchair users. Must have accessible shelter.'),

  -- Citizen self-registration
  (9, 6, 18.5200, 73.8500, 'Shivajinagar, Pune',
   FALSE, FALSE, FALSE, TRUE, 'pending',
   'Family with 3 young children looking for shelter.');

-- =============================================================================
-- ALERTS (pre-existing system alerts based on current data)
-- =============================================================================
INSERT INTO alerts (shelter_id, alert_type, severity, message) VALUES
  (2, 'critical_capacity', 'critical',
   'Shivajinagar Community Hall is at 92.7% capacity (278/300). Immediate redistribution recommended.'),

  (4, 'critical_capacity', 'critical',
   'Kothrud School Emergency Shelter is at 95.0% capacity (380/400). Accept no new groups without redistribution.'),

  (6, 'critical_capacity', 'warning',
   'Kondhwa Temporary Shelter is at 91.4% capacity (320/350). Monitor closely.'),

  (8, 'critical_capacity', 'critical',
   'Wagholi Rural Shelter is at 97.5% capacity (195/200). Do not send new groups.'),

  (8, 'resource_shortage', 'warning',
   'Wagholi Rural Shelter has critically low water supply (300 litres) and only 2 medicine kits.');
