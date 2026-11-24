"""
migrate_stage5.py — DB migration for Stage 5.

Adds new columns introduced in Stage 5:
  shelter_facilities.has_food        (TINYINT(1), NOT NULL, DEFAULT 0)
  shelter_facilities.updated_by      (INT, FK → users.id, nullable)
  resources.notes                    (TEXT, nullable)

Run once:
  python migrate_stage5.py
"""

from app import create_app
from extensions import db

app = create_app()

MIGRATIONS = [
    # Table                 | Column         | SQL type definition
    ('shelter_facilities', 'has_food',    'TINYINT(1) NOT NULL DEFAULT 0 AFTER has_medical_support'),
    ('shelter_facilities', 'updated_by',  'INT NULL'),
    ('shelter_facilities', 'notes_col',   None),   # already exists
    ('resources',          'notes',       'TEXT NULL'),
]

def column_exists(conn, table, column):
    result = conn.execute(
        db.text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
        ),
        {'t': table, 'c': column}
    )
    return result.scalar() > 0

def fk_exists(conn, table, column):
    result = conn.execute(
        db.text(
            "SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND COLUMN_NAME = :c "
            "AND REFERENCED_TABLE_NAME IS NOT NULL"
        ),
        {'t': table, 'c': column}
    )
    return result.scalar() > 0

with app.app_context():
    with db.engine.begin() as conn:

        print('Running Stage 5 migrations...\n')

        # 1. shelter_facilities.has_food
        if not column_exists(conn, 'shelter_facilities', 'has_food'):
            conn.execute(db.text(
                "ALTER TABLE shelter_facilities "
                "ADD COLUMN has_food TINYINT(1) NOT NULL DEFAULT 0 "
                "AFTER has_medical_support"
            ))
            print('  [+] shelter_facilities.has_food added')
        else:
            print('  [=] shelter_facilities.has_food already exists')

        # 2. shelter_facilities.updated_by
        if not column_exists(conn, 'shelter_facilities', 'updated_by'):
            conn.execute(db.text(
                "ALTER TABLE shelter_facilities "
                "ADD COLUMN updated_by INT NULL"
            ))
            conn.execute(db.text(
                "ALTER TABLE shelter_facilities "
                "ADD CONSTRAINT fk_sf_updated_by "
                "FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL"
            ))
            print('  [+] shelter_facilities.updated_by added (FK)')
        else:
            print('  [=] shelter_facilities.updated_by already exists')

        # 3. resources.notes
        if not column_exists(conn, 'resources', 'notes'):
            conn.execute(db.text(
                "ALTER TABLE resources ADD COLUMN notes TEXT NULL"
            ))
            print('  [+] resources.notes added')
        else:
            print('  [=] resources.notes already exists')

        print('\nAll migrations complete.')
