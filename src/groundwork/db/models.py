"""
ORM models - the single source of truth for the schema.

This project switched from hand-written Core `Table` objects + hand-written
migrations to SQLAlchemy's ORM + Alembic autogenerate. The tradeoff, made
explicitly: less time spent keeping a migration and a Table definition in
sync by hand, in exchange for trusting `alembic revision --autogenerate` to
diff these models against the live database and generate the migration for
you (which you should still *read* before running - autogenerate is a
starting draft, not something to blindly trust, especially for renames).

Every model inherits from `Base` below so they all register into one
`Base.metadata` - that's the object `migrations/env.py` points Alembic's
`target_metadata` at, which is what makes autogenerate possible at all.
"""

from datetime import datetime

from sqlalchemy import Text, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model in this project."""


class Job(Base):
    """A single job posting, normalized across Greenhouse/Ashby/Lever.
    """
    __tablename__ = "jobs"
    __table_args__ = (
        # A posting is uniquely identified by (source, ats_job_id) - this
        # is the real dedupe key upsert_job() relies on. Making it an
        # actual database constraint (not just a Python convention) is what
        # makes repeated/concurrent loads safe instead of racy.
        UniqueConstraint("source", "ats_job_id", name="uq_jobs_source_ats_job_id"),
    )
    # Primary key (Postgres SERIAL)
    id: Mapped[int] = mapped_column(primary_key=True)
    # The posting's ID as assigned by its own ATS. 
    ats_job_id: Mapped[str] = mapped_column(Text)
    # Which ATS this came from: "greenhouse" | "ashby" | "lever". ats_job_id
    source: Mapped[str] = mapped_column(Text)
    # The company's board token/slug on that ATS 
    board_token: Mapped[str] = mapped_column(Text)
    # Job title/position (SWE, AI Eng, etc)
    title: Mapped[str] = mapped_column(Text)
    # The cleaned, human/LLM-readable posting text scripts/job_text.py
    # produces - HTML stripped, and for ATS's like Lever that split
    # requirements/skills into a separate section list, already recombined.
    description: Mapped[str] = mapped_column(Text)
    # Public URL to the posting and application
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The full, untouched API response for this posting. JSONB (not JSON)
    # so Postgres can index/query into it efficiently later - kept in full
    raw_json: Mapped[dict] = mapped_column(JSONB)
    # When *we* pulled this posting - not when the ATS published it.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Profile(Base):
    """A structured profile snapshot (groundwork.extraction.schema.ExtractedProfile,
    stored as-is via model_dump()) - one JSONB blob per row rather than
    normalized per-section tables.

    Append-only history, not a singleton: every resume/profile submission
    inserts a NEW row with a new `id`, rather than overwriting one row in
    place. Nothing here is ever updated after insert - that's also why
    there's no `updated_at`, only `created_at`. `groundwork/db/profile.py`'s
    get_latest_profile() picks the most recent row as "the" current
    profile, but older submissions stay queryable rather than being
    silently discarded. Still single-user for now ("no real multi-tenant
    auth yet" is a locked-in scope decision, BUILD_PLAN.md) - a user_id
    column arrives with Slice 10's real users, to scope "latest" per user
    instead of across the whole table.
    """
    __tablename__ = "profiles"
    # Primary key (Postgres SERIAL) - a new one per submission, not reused.
    id: Mapped[int] = mapped_column(primary_key=True)
    # The full ExtractedProfile, as ExtractedProfile.model_dump() produced it.
    # JSONB (not JSON) so Postgres can index/query into it later if needed.
    data: Mapped[dict] = mapped_column(JSONB)
    # When this snapshot was submitted. Immutable - rows are never updated
    # after insert, so there's no separate updated_at to track.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))