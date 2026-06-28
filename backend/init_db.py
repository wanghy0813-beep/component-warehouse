from app.database import Base, SessionLocal, engine
from app.main import (
    ensure_database_schema,
    ensure_v04_migration_backup,
    run_v04_account_migration,
)
from app.seed import seed_categories


def main():
    ensure_v04_migration_backup()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        ensure_database_schema(connection)
    db = SessionLocal()
    try:
        run_v04_account_migration(db)
        seed_categories(db)
    finally:
        db.close()
    print("Database initialized.")


if __name__ == "__main__":
    main()
