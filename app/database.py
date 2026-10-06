from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def ensure_schema(target_engine=engine):
    """Apply small additive migrations needed by existing SQLite installations."""
    if target_engine.dialect.name != "sqlite":
        return
    people_columns = {column["name"] for column in inspect(target_engine).get_columns("people")}
    record_columns = {column["name"] for column in inspect(target_engine).get_columns("person_certificates")}
    with target_engine.begin() as connection:
        if "identity_number" not in people_columns:
            connection.execute(text("ALTER TABLE people ADD COLUMN identity_number VARCHAR(18)"))
        if "validity_start_date" not in record_columns:
            connection.execute(text("ALTER TABLE person_certificates ADD COLUMN validity_start_date DATE"))
        if "validity_end_date" not in record_columns:
            connection.execute(text("ALTER TABLE person_certificates ADD COLUMN validity_end_date DATE"))
        # Optional website details are added in place, keeping existing records intact.
        for prefix in ("certificate", "education", "renewal"):
            for suffix, column_type in (("account", "VARCHAR(200)"), ("password", "VARCHAR(1024)"), ("notes", "TEXT")):
                column = f"{prefix}_{suffix}"
                if column not in record_columns:
                    connection.execute(text(f"ALTER TABLE person_certificates ADD COLUMN {column} {column_type}"))
        # Keep the old displayed dates as the initial range, without changing expiry reminders.
        if "validity_start_date" not in record_columns and "issue_date" in record_columns:
            connection.execute(text(
                "UPDATE person_certificates SET validity_start_date = issue_date "
                "WHERE validity_start_date IS NULL AND issue_date IS NOT NULL"
            ))
        if "validity_end_date" not in record_columns and "expiry_date" in record_columns:
            connection.execute(text(
                "UPDATE person_certificates SET validity_end_date = expiry_date "
                "WHERE validity_end_date IS NULL AND expiry_date IS NOT NULL"
            ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

