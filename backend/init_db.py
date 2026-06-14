from app.database import Base, SessionLocal, engine
from app.seed import seed_categories
from sqlalchemy import text


def ensure_sqlite_columns(connection, table: str, columns: dict[str, str]) -> None:
    existing = [row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))]
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def main():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        ensure_sqlite_columns(connection, "categories", {"color": "VARCHAR(40) DEFAULT '#eef6ff'"})
        ensure_sqlite_columns(
            connection,
            "components",
            {
                "ai_summary": "TEXT",
                "ai_usage": "TEXT",
                "ai_risk_notes": "TEXT",
                "ai_pcb_notes": "TEXT",
                "ai_substitutes": "TEXT",
                "ai_tags": "VARCHAR(500)",
                "ai_confidence": "VARCHAR(40)",
                "ai_cache_key": "VARCHAR(80)",
                "ai_status": "VARCHAR(40) DEFAULT 'pending'",
                "ai_error": "TEXT",
                "ai_updated_at": "DATETIME",
                "is_hand_solder_friendly": "BOOLEAN DEFAULT 0",
                "is_power_component": "BOOLEAN DEFAULT 0",
                "is_signal_component": "BOOLEAN DEFAULT 0",
                "is_high_current": "BOOLEAN DEFAULT 0",
                "is_high_voltage": "BOOLEAN DEFAULT 0",
                "is_common": "BOOLEAN DEFAULT 0",
            },
        )
        ensure_sqlite_columns(connection, "project_bom_items", {"status": "VARCHAR(40) DEFAULT 'reserved'"})
        ensure_sqlite_columns(
            connection,
            "projects",
            {
                "ai_bom_analysis": "TEXT",
                "ai_bom_cache_key": "VARCHAR(80)",
                "ai_bom_updated_at": "DATETIME",
            },
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_project_bom_items_status ON project_bom_items(status)"))
    db = SessionLocal()
    try:
        seed_categories(db)
    finally:
        db.close()
    print("Database initialized.")


if __name__ == "__main__":
    main()
