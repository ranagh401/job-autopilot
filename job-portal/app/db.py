"""SQLite storage for the job portal."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint, create_engine, event)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            relationship, sessionmaker)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / "resumes").mkdir(exist_ok=True)

# DATABASE_URL lets the same code run on SQLite locally and on Postgres
# when hosted (Neon, Supabase, Render...). Postgres URLs are normalised
# because several providers still hand out the old "postgres://" scheme
# and require TLS.
def _database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return f"sqlite:///{DATA_DIR / 'portal.db'}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if "sslmode=" not in url and "postgresql" in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


DB_URL = _database_url()
IS_SQLITE = DB_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(
        DB_URL,
        # The scheduler and web requests write concurrently; wait for the
        # lock instead of failing with "database is locked".
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        # WAL lets readers work while a writer holds the lock.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
else:
    # Hosted Postgres drops idle connections; recycle before it does.
    engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=280,
                           pool_size=5, max_overflow=5)


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


JOB_STATUSES = ["found", "scored", "shortlisted", "tailored", "sent",
                "replied", "interview", "skipped", "closed"]


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Long enough for "jsearch-<publisher>" style values; SQLite ignores
    # the limit but Postgres rejects anything over it.
    source: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    salary: Mapped[str] = mapped_column(String(200), default="")
    posted_at: Mapped[str] = mapped_column(String(60), default="")
    # Normalised posting date, so "posted 3d ago" works across every source
    posted_dt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Experience the posting asks for, e.g. "2-4 yrs"
    experience_required: Mapped[str] = mapped_column(String(40), default="")
    exp_min_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Where the role actually is, decided by the LLM while scoring.
    country: Mapped[str] = mapped_column(String(60), default="")
    is_india: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(20), default="found", index=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_notes: Mapped[str] = mapped_column(Text, default="")
    sponsorship_likely: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    contact_email: Mapped[str] = mapped_column(String(300), default="")
    # Normalised company+title key used to suppress cross-source duplicates
    dedupe_key: Mapped[str] = mapped_column(String(200), default="", index=True)

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    resumes: Mapped[list["ResumeVersion"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    outreach: Mapped[list["Outreach"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(40), default="")  # posting/page/hunter/manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # True when this is a named human (recruiter/HR) rather than a shared
    # inbox like careers@ - named people get far better reply rates.
    is_person: Mapped[bool] = mapped_column(Boolean, default=False)
    linkedin: Mapped[str] = mapped_column(String(400), default="")
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # LLM verdict: hr / engineering / other_person / role_inbox /
    # wrong_company / unknown. Only a verified human is ever emailed.
    kind: Mapped[str] = mapped_column(String(20), default="")
    verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verify_note: Mapped[str] = mapped_column(String(300), default="")

    job: Mapped[Job] = relationship(back_populates="contacts")


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # ATS fit of this tailored resume against the job description
    ats_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ats_keyword: Mapped[float | None] = mapped_column(Float, nullable=True)
    ats_skills: Mapped[float | None] = mapped_column(Float, nullable=True)
    ats_sections: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_keywords: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship(back_populates="resumes")


class LlmUsage(Base):
    """One row per model call, so spend is a fact rather than a guess.

    Azure bills input and output at very different rates, so the two are
    kept apart; `kind` is the pipeline step, which is what makes it
    obvious where the money actually goes.
    """
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), default="", index=True)
    model: Mapped[str] = mapped_column(String(60), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime,
                                                 default=datetime.now,
                                                 index=True)


class Application(Base):
    """An application submitted through the employer's own web form."""
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    ats: Mapped[str] = mapped_column(String(30), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="prepared")
    # prepared / submitted / failed / manual_needed
    detail: Mapped[str] = mapped_column(Text, default="")
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    answers: Mapped[str] = mapped_column(Text, default="")
    resume_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime,
                                                          nullable=True)

    job: Mapped["Job"] = relationship(back_populates="applications")


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    to_email: Mapped[str] = mapped_column(String(300), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    resume_path: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft/approved/sent/failed
    message_id: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_snippet: Mapped[str] = mapped_column(Text, default="")
    # AI classification of the reply: interview / offer / rejection /
    # info_request / auto_ack / other
    reply_kind: Mapped[str] = mapped_column(String(20), default="")
    # Follow-up sequencing (day 0 -> 3 -> 7), stops as soon as they reply
    followup_n: Mapped[int] = mapped_column(Integer, default=0)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    job: Mapped[Job] = relationship(back_populates="outreach")


def safe_commit(session, attempts: int = 6) -> None:
    """Commit, waiting out a writer on the other side.

    The background scheduler and any script run alongside it are separate
    processes writing the same file. WAL plus busy_timeout covers most of
    it, but a commit can still land exactly while the other holds the
    write lock - so retry rather than lose the work.
    """
    import time as _time

    from sqlalchemy.exc import OperationalError

    for i in range(attempts):
        try:
            session.commit()
            return
        except OperationalError as e:
            if "locked" not in str(e).lower() or i == attempts - 1:
                session.rollback()
                raise
            session.rollback()
            _time.sleep(0.5 * (2 ** i))


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()


# Columns added after the first release; SQLite needs them ALTERed in.
_ADDED_COLUMNS = {
    "jobs": [("dedupe_key", "VARCHAR(200) DEFAULT ''"),
             ("posted_dt", "DATETIME"),
             ("experience_required", "VARCHAR(40) DEFAULT ''"),
             ("exp_min_years", "FLOAT"),
             ("country", "VARCHAR(60) DEFAULT ''"),
             ("is_india", "BOOLEAN")],
    "contacts": [("is_person", "BOOLEAN DEFAULT 0"),
                 ("linkedin", "VARCHAR(400) DEFAULT ''"),
                 ("confidence", "INTEGER"),
                 ("kind", "VARCHAR(20) DEFAULT ''"),
                 ("verified", "BOOLEAN"),
                 ("verify_note", "VARCHAR(300) DEFAULT ''")],
    "resume_versions": [
        ("ats_score", "FLOAT"), ("ats_keyword", "FLOAT"),
        ("ats_skills", "FLOAT"), ("ats_sections", "FLOAT"),
        ("missing_keywords", "TEXT DEFAULT ''"),
    ],
    "outreach": [
        ("reply_kind", "VARCHAR(20) DEFAULT ''"),
        ("followup_n", "INTEGER DEFAULT 0"),
        ("parent_id", "INTEGER"),
    ],
}


def _migrate() -> None:
    """Add columns introduced after the first release.

    create_all() only creates missing TABLES, not missing columns, so an
    existing database needs them ALTERed in. Postgres supports IF NOT
    EXISTS here; SQLite does not, so it is asked what it already has.
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if IS_SQLITE:
                have = {row[1] for row in
                        conn.exec_driver_sql(f"PRAGMA table_info({table})")}
                for name, ddl in cols:
                    if name not in have:
                        conn.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            else:
                for name, ddl in cols:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} "
                        f"ADD COLUMN IF NOT EXISTS {name} {ddl}")
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_dedupe_key "
            "ON jobs (dedupe_key)"))
