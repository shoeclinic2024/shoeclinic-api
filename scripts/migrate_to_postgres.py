# scripts/migrate_to_postgres.py
import os
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

def migrate():
    """
    Migrates data from local SQLite to a remote PostgreSQL database.
    Usage: Set DATABASE_URL in .env to your PostgreSQL string.
    """
    sqlite_url = "sqlite:///instance/shoeclinic.db" # Standard Flask instance folder path or project root
    if not os.path.exists("instance/shoeclinic.db") and os.path.exists("shoeclinic.db"):
        sqlite_url = "sqlite:///shoeclinic.db"
        
    postgres_url = os.getenv("DATABASE_URL")
    
    if not postgres_url or "sqlite" in postgres_url:
        print("Error: DATABASE_URL not set to a PostgreSQL connection string.")
        return

    if postgres_url.startswith("postgres://"):
        postgres_url = postgres_url.replace("postgres://", "postgresql://", 1)

    print(f"Migrating from {sqlite_url} to {postgres_url.split('@')[-1]}...")

    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(postgres_url)

    metadata = MetaData()
    metadata.reflect(bind=sqlite_engine)

    # Create all tables in PostgreSQL based on SQLite schema
    print("Creating tables in PostgreSQL...")
    metadata.create_all(pg_engine)

    for table in metadata.sorted_tables:
        print(f"Migrating table: {table.name}")
        with sqlite_engine.connect() as sqlite_conn:
            data = sqlite_conn.execute(table.select()).fetchall()
            if data:
                with pg_engine.connect() as pg_conn:
                    # Clear existing data in target table to avoid duplicates during retry
                    pg_conn.execute(table.delete())
                    # Convert to list of dicts for bulk insert
                    rows = [dict(row._mapping) for row in data]
                    pg_conn.execute(table.insert(), rows)
                    pg_conn.commit()
                print(f"  Inserted {len(rows)} rows.")
            else:
                print("  No data found.")

    print("Migration complete!")

if __name__ == "__main__":
    migrate()
