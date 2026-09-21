"""
Data access for the `jobs` table - the one place queries for jobs get
written.

Both the Slice 1 loader (writes) and the Slice 3 agent (reads, via a
`get_job` tool) import from here instead of running their own queries -
that's what "shared data-access module" means in CLAUDE.md's architecture
rules: the API and the agent both reach Postgres through modules like this
one, never through each other.
"""

from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jobsentinel.db.models import Job


def upsert_job(engine: Engine, job: dict) -> int:
    """Insert a normalized job dict (see scripts/job_text.normalized_job),
    or overwrite it in place if (source, ats_job_id) already exists.

    Returns the row's internal `id` either way - callers refer to the job
    by that afterwards, not by ats_job_id (see get_job below).

    Why this isn't a "pure ORM" Session.add()/merge() call: SQLAlchemy's
    ORM has no native atomic upsert. Session.merge() does a SELECT then an
    INSERT-or-UPDATE - not atomic, and it needs the primary key already
    known, which defeats the point since we're deduping on (source,
    ats_job_id), not `id`. Postgres's own `INSERT ... ON CONFLICT DO
    UPDATE` is the correct tool for that, and SQLAlchemy exposes it as an
    Insert statement built directly off the model's table - `Job.__table__`
    is the exact same Core Table object the ORM itself queries against, so
    this isn't a workaround, it's the standard way to do a real upsert even
    in an otherwise fully-ORM codebase.
    """
    # job["fetched_at"] arrives as an ISO 8601 string (that's what
    # job_text.normalized_job produces). psycopg needs an actual datetime
    # object to bind against a `timestamptz` column - parsing it back here,
    # once, means every caller of upsert_job doesn't have to think about it.
    fetched_at = datetime.fromisoformat(job["fetched_at"])

    stmt = pg_insert(Job.__table__).values(
        ats_job_id=job["ats_job_id"],
        source=job["source"],
        board_token=job["board_token"],
        title=job["title"],
        description=job["description"],
        url=job["url"],
        raw_json=job["raw_json"],
        fetched_at=fetched_at,
    )

    # ON CONFLICT (source, ats_job_id) DO UPDATE ... - this is what makes
    # re-running the loader against a board you've already loaded safe
    # (overwrite in place) instead of erroring on the unique constraint or
    # silently duplicating rows. `stmt.excluded` refers to the row Postgres
    # *tried* to insert and rejected - i.e. the fresh values from this call.
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "ats_job_id"],
        set_={
            "board_token": stmt.excluded.board_token,
            "title": stmt.excluded.title,
            "description": stmt.excluded.description,
            "url": stmt.excluded.url,
            "raw_json": stmt.excluded.raw_json,
            "fetched_at": stmt.excluded.fetched_at,
        },
    ).returning(Job.__table__.c.id)

    # engine.begin() opens a transaction that commits automatically if the
    # block exits cleanly, and rolls back if anything raises.
    with engine.begin() as conn:
        result = conn.execute(stmt)
        return result.scalar_one()


def get_job(engine: Engine, job_id: int) -> dict | None:
    """Fetch one job by its internal `id` - NOT its ats_job_id.

    Returns a plain dict, not the live `Job` ORM object, on purpose: the
    object is tied to the Session opened in this function, which is closed
    before we return. Handing back the object itself would risk the
    classic ORM DetachedInstanceError the moment a caller - including the
    agent's `get_job` tool in Slice 3 - touches an attribute after that
    session is gone. A plain dict has no such lifetime to worry about.
    """
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "ats_job_id": job.ats_job_id,
            "source": job.source,
            "board_token": job.board_token,
            "title": job.title,
            "description": job.description,
            "url": job.url,
            "raw_json": job.raw_json,
            "fetched_at": job.fetched_at,
        }


def list_jobs(engine: Engine) -> list[dict]:
    """Every job, ordered by internal id, projected to summary fields only.

    Deliberately excludes `description`/`raw_json` - those are large text
    blobs only needed on the single-job detail view (get_job above), and
    including them here would make a ~600-row response unnecessarily big.

    No pagination or filtering params: today's only loaded board fits
    comfortably in one response as summaries, and positions.py-based
    filtering (or scoping by followed company) is real future job-feed
    work, not something to build ahead of an actual need.
    """
    stmt = select(
        Job.id,
        Job.title,
        Job.source,
        Job.board_token,
        Job.url,
        Job.fetched_at,
    ).order_by(Job.id)
    with Session(engine) as session:
        return [dict(row._mapping) for row in session.execute(stmt)]
