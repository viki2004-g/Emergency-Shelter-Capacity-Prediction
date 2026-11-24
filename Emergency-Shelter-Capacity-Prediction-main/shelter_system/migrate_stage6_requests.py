"""
migrate_stage6_requests.py — Database migration for Shelter Requests.

Adds new columns to shelter_requests:
  - requesting_team             VARCHAR(150) NULL
  - contact_phone               VARCHAR(50)  NULL
  - injured_count               INT NOT NULL DEFAULT 0
  - elderly_count               INT NOT NULL DEFAULT 0
  - children_count              INT NOT NULL DEFAULT 0
  - accessibility_requirements  TEXT NULL
  - medical_requirements        TEXT NULL
  - other_special_requirements  TEXT NULL
"""

import sys
from sqlalchemy import text
from app import create_app
from extensions import db


def run_migration():
    app = create_app()
    with app.app_context():
        print("Checking existing columns in shelter_requests...")
        result = db.session.execute(text("DESCRIBE shelter_requests"))
        existing_cols = {row[0] for row in result}

        migrations = [
            (
                "requesting_team",
                "ALTER TABLE shelter_requests ADD COLUMN requesting_team VARCHAR(150) NULL AFTER location_name"
            ),
            (
                "contact_phone",
                "ALTER TABLE shelter_requests ADD COLUMN contact_phone VARCHAR(50) NULL AFTER requesting_team"
            ),
            (
                "injured_count",
                "ALTER TABLE shelter_requests ADD COLUMN injured_count INT NOT NULL DEFAULT 0 AFTER contact_phone"
            ),
            (
                "elderly_count",
                "ALTER TABLE shelter_requests ADD COLUMN elderly_count INT NOT NULL DEFAULT 0 AFTER injured_count"
            ),
            (
                "children_count",
                "ALTER TABLE shelter_requests ADD COLUMN children_count INT NOT NULL DEFAULT 0 AFTER elderly_count"
            ),
            (
                "accessibility_requirements",
                "ALTER TABLE shelter_requests ADD COLUMN accessibility_requirements TEXT NULL AFTER children_count"
            ),
            (
                "medical_requirements",
                "ALTER TABLE shelter_requests ADD COLUMN medical_requirements TEXT NULL AFTER accessibility_requirements"
            ),
            (
                "other_special_requirements",
                "ALTER TABLE shelter_requests ADD COLUMN other_special_requirements TEXT NULL AFTER medical_requirements"
            ),
        ]

        for col_name, sql in migrations:
            if col_name not in existing_cols:
                print(f"  Adding column '{col_name}'...")
                db.session.execute(text(sql))
            else:
                print(f"  Column '{col_name}' already exists.")

        db.session.commit()
        print("Shelter requests migration completed successfully!")


if __name__ == '__main__':
    run_migration()
