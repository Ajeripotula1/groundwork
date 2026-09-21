"""
Data access for the `profiles` table - the one place profile reads/writes
happen. Both the API (Slice 2) and the agent (Slice 3's query_profile_facts
tool) import from here rather than running their own queries - same
shared-data-access pattern as jobsentinel.db.jobs.

Append-only history: every submission inserts a new row rather than
overwriting one. get_latest_profile() is what makes that look like a
single "current profile" to callers - it's just the most recent row.
"""

from datetime import datetime, timezone

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jobsentinel.db.models import Profile


def insert_profile(engine: Engine, data: dict, user_id: str) -> dict:
    """Insert a new profile snapshot owned by `user_id` and return it (with
    its assigned id and created_at). Every call creates a new row - there's
    no update path, same reasoning as jobsentinel.db.jobs.upsert_job for
    using a Core INSERT statement rather than the ORM's Session.add() (this
    keeps the return shape - a plain dict, not a live ORM object -
    consistent with the rest of this module's functions).
    """
    now = datetime.now(timezone.utc)

    stmt = (
        pg_insert(Profile.__table__)
        .values(data=data, user_id=user_id, created_at=now)
        .returning(
            Profile.__table__.c.id,
            Profile.__table__.c.data,
            Profile.__table__.c.created_at,
        )
    )

    with engine.begin() as conn:
        row = conn.execute(stmt).one()
        return {"id": row.id, "data": row.data, "created_at": row.created_at}


def get_profile(engine: Engine, profile_id: int, user_id: str | None = None) -> dict | None:
    """Fetch one profile snapshot by id, or None if it doesn't exist.

    `user_id`: pass the *authenticated caller's* id whenever `profile_id`
    came from client input (a query param/request body) rather than from a
    trusted internal source - this enforces ownership, returning None (the
    same "not found" a bad id gets) rather than another user's data, so a
    caller can't tell "wrong id" apart from "someone else's id" by probing.
    Every API route that accepts a profile_id must pass this. Left as None
    only for closure-bound call sites where profile_id was already resolved
    and ownership-checked upstream in the same request (e.g. the Job
    Agent's get_profile_facts tool - see job_agent.agent.build_tools).

    Returns a plain dict, not the live Profile ORM object - see
    jobsentinel.db.jobs.get_job's docstring for why (avoids
    DetachedInstanceError once the session this function opened is closed).
    """
    with Session(engine) as session:
        conditions = [Profile.id == profile_id]
        if user_id is not None:
            conditions.append(Profile.user_id == user_id)
        stmt = select(Profile).where(*conditions)
        profile = session.execute(stmt).scalar_one_or_none()
        if profile is None:
            return None
        return {"id": profile.id, "data": profile.data, "created_at": profile.created_at}


def get_latest_profile(engine: Engine, user_id: str) -> dict | None:
    """Fetch `user_id`'s most recently submitted profile, or None if they
    haven't submitted one yet. "Latest" is by `id` (an ever-increasing
    sequence), not `created_at` - safe even if two submissions land in the
    same instant.

    Added back alongside get_profile(id) for Slice 3's query_profile_facts
    tool: the CLI only takes a job_id, not a profile_id, so the agent needs
    a "give me the current profile" call - same "most recent row is the
    current one" reasoning as the Profile model's docstring. get_profile(id)
    still exists separately for fetching a specific historical snapshot
    (e.g. GET /profile?id=<id>).
    """
    with Session(engine) as session:
        stmt = (
            select(Profile)
            .where(Profile.user_id == user_id)
            .order_by(Profile.id.desc())
            .limit(1)
        )
        profile = session.execute(stmt).scalar_one_or_none()
        if profile is None:
            return None
        return {"id": profile.id, "data": profile.data, "created_at": profile.created_at}
