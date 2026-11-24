"""
db_init.py — Database initialisation script.

Run this ONCE after:
  1. Creating the MySQL database:  CREATE DATABASE shelter_system;
  2. Setting up your .env file with correct DB credentials.

Usage:
  python db_init.py           # create tables + insert seed data
  python db_init.py --no-seed # create tables only (no sample data)

What this script does:
  1. Creates all tables defined in the SQLAlchemy models.
  2. Optionally inserts realistic seed data for development and testing.

IMPORTANT: Do NOT run this on a database that already has live data.
           db.create_all() is safe (it won't drop existing tables),
           but the seed data insert will fail if records already exist.
"""

import sys
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

from app import create_app
from extensions import db
from models import (
    User, Shelter, ShelterFacility, Resource,
    OccupancyHistory, ShelterRequest, Allocation, Alert
)


def create_tables(app):
    """Create all tables in MySQL based on SQLAlchemy models."""
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("All tables created successfully.")


def seed_data(app):
    """Insert realistic seed data for development."""
    with app.app_context():

        # ── Check if data already exists ─────────────────────────────────────
        if User.query.first():
            print("Seed data already exists — skipping.")
            return

        print("Inserting seed data...")

        # ── Password for ALL seed users ──────────────────────────────────────
        # In Stage 3, Flask-Bcrypt replaces werkzeug hashing.
        # Use this password to log in during development: Password@123
        demo_pw = generate_password_hash('Password@123')

        # ── Users ─────────────────────────────────────────────────────────────
        admin     = User(full_name='System Administrator',  email='admin@shelter.gov',     password_hash=demo_pw, role='admin')
        authority = User(full_name='District Authority',    email='authority@shelter.gov',  password_hash=demo_pw, role='authority')
        resp1     = User(full_name='Rahul Sharma',          email='responder1@shelter.gov', password_hash=demo_pw, role='responder')
        resp2     = User(full_name='Priya Nair',            email='responder2@shelter.gov', password_hash=demo_pw, role='responder')
        mgr1      = User(full_name='Amit Kulkarni',         email='manager1@shelter.gov',   password_hash=demo_pw, role='shelter_manager')
        mgr2      = User(full_name='Sunita Desai',          email='manager2@shelter.gov',   password_hash=demo_pw, role='shelter_manager')
        mgr3      = User(full_name='Vikram Patel',          email='manager3@shelter.gov',   password_hash=demo_pw, role='shelter_manager')
        mgr4      = User(full_name='Meena Joshi',           email='manager4@shelter.gov',   password_hash=demo_pw, role='shelter_manager')
        citizen   = User(full_name='Citizen User',          email='citizen@example.com',    password_hash=demo_pw, role='citizen')

        db.session.add_all([admin, authority, resp1, resp2, mgr1, mgr2, mgr3, mgr4, citizen])
        db.session.flush()  # flush to get user IDs before using them as FKs

        # ── Shelters — real Pune, Maharashtra coordinates ──────────────────────
        s1 = Shelter(name='Deccan Gymkhana Relief Centre',
                     address='Deccan Gymkhana, Pune 411004',
                     latitude=18.516700, longitude=73.838900,
                     max_capacity=500, current_occupancy=312,
                     status='active', managed_by=mgr1.id,
                     notes='Primary flood relief centre for west Pune. Ground floor accessible.')

        s2 = Shelter(name='Shivajinagar Community Hall',
                     address='FC Road, Shivajinagar, Pune 411005',
                     latitude=18.530800, longitude=73.847400,
                     max_capacity=300, current_occupancy=278,
                     status='active', managed_by=mgr2.id,
                     notes='Near bus terminus. Good access for rescue vehicles.')

        s3 = Shelter(name='Hadapsar Sports Complex',
                     address='Hadapsar, Pune 411028',
                     latitude=18.501800, longitude=73.925200,
                     max_capacity=600, current_occupancy=130,
                     status='active', managed_by=mgr3.id,
                     notes='Largest shelter in east Pune. Open area for overflow tents.')

        s4 = Shelter(name='Kothrud School Emergency Shelter',
                     address='Kothrud, Pune 411038',
                     latitude=18.507400, longitude=73.807700,
                     max_capacity=400, current_occupancy=380,
                     status='active', managed_by=mgr4.id,
                     notes='School premises. Separate rooms for families and medical cases.')

        s5 = Shelter(name='Baner Relief Camp',
                     address='Baner Road, Pune 411045',
                     latitude=18.560000, longitude=73.785500,
                     max_capacity=250, current_occupancy=60,
                     status='active', managed_by=mgr1.id,
                     notes='Newer facility. Fully equipped kitchen and medical bay.')

        s6 = Shelter(name='Kondhwa Temporary Shelter',
                     address='Kondhwa Budruk, Pune 411048',
                     latitude=18.468600, longitude=73.880800,
                     max_capacity=350, current_occupancy=320,
                     status='active', managed_by=mgr2.id,
                     notes='Approaching capacity. Monitor closely.')

        s7 = Shelter(name='PCMC Pimpri Relief Centre',
                     address='Pimpri-Chinchwad, Pune 411018',
                     latitude=18.629800, longitude=73.799700,
                     max_capacity=450, current_occupancy=90,
                     status='active', managed_by=mgr3.id,
                     notes='Industrial area shelter. Suitable for large group redistribution.')

        s8 = Shelter(name='Wagholi Rural Shelter',
                     address='Wagholi, Pune 412207',
                     latitude=18.569700, longitude=73.982600,
                     max_capacity=200, current_occupancy=195,
                     status='active', managed_by=mgr4.id,
                     notes='Near capacity. Limited medical facilities.')

        db.session.add_all([s1, s2, s3, s4, s5, s6, s7, s8])
        db.session.flush()  # flush to get shelter IDs

        # ── Shelter Facilities ─────────────────────────────────────────────────
        db.session.add_all([
            ShelterFacility(shelter_id=s1.id, has_medical_support=True,  has_wheelchair_access=True,  has_electricity=True,  has_toilets=True,  has_running_water=True,  has_kitchen=True,  has_family_area=True),
            ShelterFacility(shelter_id=s2.id, has_medical_support=False, has_wheelchair_access=False, has_electricity=True,  has_toilets=True,  has_running_water=True,  has_kitchen=False, has_family_area=False),
            ShelterFacility(shelter_id=s3.id, has_medical_support=True,  has_wheelchair_access=True,  has_electricity=True,  has_toilets=True,  has_running_water=True,  has_kitchen=True,  has_family_area=True),
            ShelterFacility(shelter_id=s4.id, has_medical_support=True,  has_wheelchair_access=False, has_electricity=True,  has_toilets=True,  has_running_water=True,  has_kitchen=True,  has_family_area=True),
            ShelterFacility(shelter_id=s5.id, has_medical_support=True,  has_wheelchair_access=True,  has_electricity=True,  has_toilets=True,  has_running_water=True,  has_kitchen=True,  has_family_area=False),
            ShelterFacility(shelter_id=s6.id, has_medical_support=False, has_wheelchair_access=False, has_electricity=True,  has_toilets=True,  has_running_water=True,  has_kitchen=False, has_family_area=False),
            ShelterFacility(shelter_id=s7.id, has_medical_support=False, has_wheelchair_access=True,  has_electricity=True,  has_toilets=True,  has_running_water=True,  has_kitchen=True,  has_family_area=False),
            ShelterFacility(shelter_id=s8.id, has_medical_support=False, has_wheelchair_access=False, has_electricity=False, has_toilets=True,  has_running_water=False, has_kitchen=False, has_family_area=False),
        ])

        # ── Resources ─────────────────────────────────────────────────────────
        db.session.add_all([
            Resource(shelter_id=s1.id, beds_available=420, food_portions=600, water_litres=2000, medicine_kits=30, blankets=450, updated_by=mgr1.id),
            Resource(shelter_id=s2.id, beds_available=280, food_portions=300, water_litres=900,  medicine_kits=5,  blankets=260, updated_by=mgr2.id),
            Resource(shelter_id=s3.id, beds_available=580, food_portions=800, water_litres=3000, medicine_kits=40, blankets=580, updated_by=mgr3.id),
            Resource(shelter_id=s4.id, beds_available=380, food_portions=400, water_litres=1200, medicine_kits=25, blankets=390, updated_by=mgr4.id),
            Resource(shelter_id=s5.id, beds_available=230, food_portions=300, water_litres=1000, medicine_kits=20, blankets=240, updated_by=mgr1.id),
            Resource(shelter_id=s6.id, beds_available=330, food_portions=350, water_litres=800,  medicine_kits=3,  blankets=310, updated_by=mgr2.id),
            Resource(shelter_id=s7.id, beds_available=440, food_portions=550, water_litres=1800, medicine_kits=15, blankets=420, updated_by=mgr3.id),
            Resource(shelter_id=s8.id, beds_available=180, food_portions=200, water_litres=300,  medicine_kits=2,  blankets=160, updated_by=mgr4.id),
        ])

        # ── Occupancy History — 48 hours of snapshots ──────────────────────────
        # This data is used by the prediction engine (Stage 10)
        now = datetime.utcnow()

        def h(shelter_id, occupancy, hours_ago):
            return OccupancyHistory(
                shelter_id=shelter_id,
                occupancy=occupancy,
                recorded_at=now - timedelta(hours=hours_ago),
                recorded_by=admin.id
            )

        history_records = [
            # Shelter 1 — Deccan Gymkhana (steady arrivals)
            h(s1.id, 120, 48), h(s1.id, 180, 42), h(s1.id, 220, 36),
            h(s1.id, 260, 24), h(s1.id, 290, 12), h(s1.id, 312, 2),

            # Shelter 2 — Shivajinagar (rapid fill — nearing critical)
            h(s2.id, 50,  48), h(s2.id, 120, 36), h(s2.id, 200, 24),
            h(s2.id, 250, 12), h(s2.id, 270, 6),  h(s2.id, 278, 1),

            # Shelter 3 — Hadapsar (low usage, plenty of space)
            h(s3.id, 20,  48), h(s3.id, 50,  36), h(s3.id, 80,  24),
            h(s3.id, 110, 12), h(s3.id, 125, 3),  h(s3.id, 130, 1),

            # Shelter 4 — Kothrud (high — approaching critical)
            h(s4.id, 200, 48), h(s4.id, 280, 36), h(s4.id, 330, 24),
            h(s4.id, 360, 12), h(s4.id, 375, 4),  h(s4.id, 380, 1),

            # Shelter 5 — Baner (light use)
            h(s5.id, 10,  48), h(s5.id, 20,  36), h(s5.id, 35,  24),
            h(s5.id, 50,  12), h(s5.id, 58,  2),  h(s5.id, 60,  1),

            # Shelter 6 — Kondhwa (filling fast — close to capacity)
            h(s6.id, 100, 48), h(s6.id, 180, 36), h(s6.id, 240, 24),
            h(s6.id, 290, 12), h(s6.id, 310, 4),  h(s6.id, 320, 1),

            # Shelter 7 — PCMC Pimpri (slow fill, lots of space)
            h(s7.id, 20,  48), h(s7.id, 40,  36), h(s7.id, 60,  24),
            h(s7.id, 75,  12), h(s7.id, 88,  3),  h(s7.id, 90,  1),

            # Shelter 8 — Wagholi (near capacity, very limited)
            h(s8.id, 80,  48), h(s8.id, 120, 36), h(s8.id, 155, 24),
            h(s8.id, 175, 12), h(s8.id, 190, 4),  h(s8.id, 195, 1),
        ]
        db.session.add_all(history_records)

        # ── Shelter Requests ───────────────────────────────────────────────────
        req1 = ShelterRequest(
            submitted_by=resp1.id,
            group_size=150,
            latitude=18.3667, longitude=73.7555,
            location_name='Sinhagad Road, Pune',
            has_injured=True, has_elderly=True, has_disabled=False, has_children=True,
            status='pending',
            notes='Flood evacuation. 5 injured, 15 elderly, 30 children. Medical priority needed.'
        )
        req2 = ShelterRequest(
            submitted_by=resp2.id,
            group_size=45,
            latitude=18.4530, longitude=73.8650,
            location_name='Katraj, Pune',
            has_injured=False, has_elderly=True, has_disabled=True, has_children=False,
            status='pending',
            notes='8 elderly, 4 wheelchair users. Must have accessible shelter.'
        )
        req3 = ShelterRequest(
            submitted_by=citizen.id,
            group_size=6,
            latitude=18.5200, longitude=73.8500,
            location_name='Shivajinagar, Pune',
            has_injured=False, has_elderly=False, has_disabled=False, has_children=True,
            status='pending',
            notes='Family with 3 young children.'
        )
        db.session.add_all([req1, req2, req3])

        # ── Alerts ────────────────────────────────────────────────────────────
        db.session.add_all([
            Alert(shelter_id=s2.id, alert_type='critical_capacity', severity='critical',
                  message='Shivajinagar Community Hall is at 92.7% capacity (278/300). Immediate redistribution recommended.'),
            Alert(shelter_id=s4.id, alert_type='critical_capacity', severity='critical',
                  message='Kothrud School Emergency Shelter is at 95.0% capacity (380/400). Do not send new groups without redistribution.'),
            Alert(shelter_id=s6.id, alert_type='critical_capacity', severity='warning',
                  message='Kondhwa Temporary Shelter is at 91.4% capacity (320/350). Monitor closely.'),
            Alert(shelter_id=s8.id, alert_type='critical_capacity', severity='critical',
                  message='Wagholi Rural Shelter is at 97.5% capacity (195/200). Do not send new groups.'),
            Alert(shelter_id=s8.id, alert_type='resource_shortage', severity='warning',
                  message='Wagholi Rural Shelter has critically low water (300L) and only 2 medicine kits.'),
        ])

        # ── Commit everything ─────────────────────────────────────────────────
        db.session.commit()
        print("Seed data inserted successfully.")
        print("\nSeed users (password for all: Password@123):")
        print("  admin@shelter.gov        — admin")
        print("  authority@shelter.gov    — authority")
        print("  responder1@shelter.gov   — responder")
        print("  manager1@shelter.gov     — shelter_manager")
        print("  citizen@example.com      — citizen")


def verify_data(app):
    """Quick verification: print counts for each table."""
    with app.app_context():
        print("\n--- Verification -------------------------------------------")
        print(f"  users              : {User.query.count()}")
        print(f"  shelters           : {Shelter.query.count()}")
        print(f"  shelter_facilities : {ShelterFacility.query.count()}")
        print(f"  resources          : {Resource.query.count()}")
        print(f"  occupancy_history  : {OccupancyHistory.query.count()}")
        print(f"  shelter_requests   : {ShelterRequest.query.count()}")
        print(f"  allocations        : {Allocation.query.count()}")
        print(f"  alerts             : {Alert.query.count()}")

        # Verify relationship: shelter -> facility
        shelter = Shelter.query.first()
        print(f"\n  Relationship check:")
        print(f"  Shelter  : {shelter.name}")
        print(f"  Facility : medical={shelter.facility.has_medical_support}, "
              f"wheelchair={shelter.facility.has_wheelchair_access}")
        print(f"  Resource : beds={shelter.resource.beds_available}, "
              f"food={shelter.resource.food_portions}")
        print(f"  History  : {shelter.occupancy_history.count()} records")
        print(f"  Occupancy: {shelter.current_occupancy}/{shelter.max_capacity} "
              f"({shelter.occupancy_pct}%)")
        print("------------------------------------------------------------")


if __name__ == '__main__':
    insert_seed = '--no-seed' not in sys.argv
    flask_app = create_app()

    create_tables(flask_app)

    if insert_seed:
        seed_data(flask_app)
        verify_data(flask_app)
    else:
        print("Skipped seed data (--no-seed flag was set).")
