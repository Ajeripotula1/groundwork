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
from decimal import Decimal

from sqlalchemy import Text, DateTime, ForeignKey, Numeric, UniqueConstraint
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


class AgentRun(Base):
    """One invocation of the agent loop (BUILD_PLAN.md Slice 3) - e.g. one
    call to groundwork.agent.score_fit.agent's invoke(). Token/cost
    accounting lives here from the start (the stack's "token budgets belong
    in the schema from day one" principle - see CLAUDE.md), rather than
    being bolted on once cost actually becomes a problem.

    Unlike Job/Profile, this row IS updated after insert: `started_at` is
    set when the run begins (before the model is ever called - so a crash
    mid-run still leaves a row behind, not a silent gap), then `ended_at`/
    `outcome`/token counts/`cost_usd` are filled in once the run finishes
    or fails. See groundwork.db.agent_runs.start_run/end_run.
    """
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    # Which job this run scored/processed. No ORM relationship() on
    # purpose - every data-access function in this project hands back plain
    # dicts, not live ORM objects (see Profile's docstring for why), so
    # there's nothing for a relationship() to usefully load.
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    # Which capability this run was for - "score_fit" today, "job_agent"
    # once Slice 5 lands. This is what makes "has Score Fit succeeded for
    # job X" a real query (get_latest_run in groundwork.db.agent_runs)
    # instead of scanning every row regardless of which capability produced
    # it. Server default backfills existing rows (all score_fit so far, per
    # the migration) without requiring a value on every historical insert.
    kind: Mapped[str] = mapped_column(Text, server_default="score_fit")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Nullable: unset until the run finishes (successfully or not).
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Short human-readable status, e.g. "success" or "error: <message>" -
    # not the model's actual output, which lives in `result` below.
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The run's structured output - groundwork.agent.shared.schema.FitAssessment.
    # model_dump(), once the run succeeds. JSONB (queryable), not the
    # response text: this is what the Slice 5 Job Agent and the eventual UI
    # read instead of re-parsing prose. Null until end_run() records success.
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    # Numeric, not float - this is money. 10 total digits, 6 after the
    # decimal point: enough headroom for a very expensive run while still
    # tracking fractions of a cent (a single Sonnet call here costs cents,
    # not dollars).
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)


class ToolCall(Base):
    """One tool invocation within an AgentRun - the audit trail Slice 4's
    eval harness checks against (e.g. "both tools were called exactly
    once," "no call had empty args") instead of asserting on model output
    text directly.
    """
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"))
    tool_name: Mapped[str] = mapped_column(Text)
    # JSONB, not Text: both are small structured payloads (tool args, tool
    # results) worth being able to query into later, same reasoning as
    # Job.raw_json/Profile.data.
    args: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))