"""Copy the local SQLite database into a hosted Postgres.

    set DATABASE_URL=postgresql://...neon.tech/neondb?sslmode=require
    python migrate_to_postgres.py

Safe to re-run: it refuses to touch a target that already has jobs
unless --replace is given.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.db import (Application, Base, Contact, Job, Outreach,  # noqa: E402
                    ResumeVersion)

# Order matters: parents before the rows that reference them.
TABLES = [Job, Contact, ResumeVersion, Outreach, Application]


def main() -> int:
    target_url = (os.getenv("DATABASE_URL") or "").strip()
    if not target_url or target_url.startswith("sqlite"):
        print("Set DATABASE_URL to the Postgres connection string first.")
        return 1
    if target_url.startswith("postgres://"):
        target_url = target_url.replace(
            "postgres://", "postgresql+psycopg2://", 1)
    elif target_url.startswith("postgresql://"):
        target_url = target_url.replace(
            "postgresql://", "postgresql+psycopg2://", 1)
    if "sslmode=" not in target_url:
        target_url += ("&" if "?" in target_url else "?") + "sslmode=require"

    sqlite_path = ROOT / "data" / "portal.db"
    if not sqlite_path.exists():
        print(f"no local database at {sqlite_path}")
        return 1

    src = create_engine(f"sqlite:///{sqlite_path}",
                        connect_args={"check_same_thread": False})
    dst = create_engine(target_url, pool_pre_ping=True)
    SrcSession = sessionmaker(bind=src)
    DstSession = sessionmaker(bind=dst)

    if "--fresh" in sys.argv:
        print("dropping existing tables on the target...")
        Base.metadata.drop_all(dst)
    print("creating tables on the target...")
    Base.metadata.create_all(dst)

    s, d = SrcSession(), DstSession()
    try:
        existing = d.execute(select(Job.id).limit(1)).first()
        if existing and "--replace" not in sys.argv:
            print("target already has jobs - re-run with --replace to "
                  "overwrite, or point at an empty database.")
            return 1
        if existing:
            print("clearing the target...")
            for model in reversed(TABLES):
                d.query(model).delete()
            d.commit()

        for model in TABLES:
            rows = s.query(model).all()
            for row in rows:
                data = {c.name: getattr(row, c.name)
                        for c in model.__table__.columns}
                d.merge(model(**data))
            d.commit()
            print(f"  {model.__tablename__:<18} {len(rows)} rows")

        # Postgres sequences must be moved past the copied ids.
        if dst.dialect.name == "postgresql":
            for model in TABLES:
                t = model.__tablename__
                d.execute(select(1))
                d.connection().exec_driver_sql(
                    f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {t}), 1), true)")
            d.commit()
            print("id sequences reset")

        print("\nmigration complete")
        return 0
    finally:
        s.close()
        d.close()


if __name__ == "__main__":
    sys.exit(main())
