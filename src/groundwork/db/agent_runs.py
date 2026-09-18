"""Data access for `agent_runs`/`tool_calls` - the audit trail for every
agent invocation (BUILD_PLAN.md Slice 3). Same shared-data-access pattern
as groundwork.db.jobs/profile: the agent's CLI/tools are the only callers
today, but this stays a separate module (not inlined into groundwork.agent)
so the API can read run history directly later without reaching into the
agent package - same hard architectural rule as everywhere else.

Unlike jobs/profiles, an AgentRun row is mutated after insert: start_run()
opens it (so a crash mid-run still leaves a row - a stuck run with a null
ended_at is itself useful signal), end_run() fills in the outcome.

`kind` (Slice 5's gating-requirement design exercise, BUILD_PLAN.md) turns
"has Score Fit succeeded for job X" from a re-run into a query:
get_latest_run/get_latest_successful_result filter on it directly, rather
than a separate scores table duplicating what's already in `result`. Kept
as a plain column on agent_runs (not a new table) because every real
access pattern so far is "one job at a time" (the Job Agent gate, and a
user revisiting a job to see its cached score) - a materialized table only
starts earning its keep once something needs to list scores for many jobs
at once (Slice 7's job feed), and isn't needed until then.
"""

from datetime import datetime, timezone

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from groundwork.db.models import AgentRun, ToolCall

# Kept as constants, not free strings, so every caller/query spells them
# identically - get_latest_run/get_latest_successful_result below are
# useless if a typo'd kind silently never matches.
KIND_SCORE_FIT = "score_fit"
# One AgentRun per Job Agent *turn* (Slice 5), not one per whole
# conversation - a turn is one invocation of the agent loop, same
# definition this table already uses for Score Fit, and it's what lets
# per-turn token/cost accounting fall out for free instead of needing a
# separate running total.
KIND_JOB_AGENT = "job_agent"


def start_run(engine: Engine, job_id: int, kind: str = KIND_SCORE_FIT) -> dict:
    """Open a new agent run for `job_id` and return it (with its assigned
    id and started_at). Call this before the agent ever touches Bedrock -
    a run row should exist even if the process crashes or the model call
    fails.

    `kind` distinguishes which capability this run is for ("score_fit" vs.
    the future "job_agent") - see get_latest_run, which filters on it.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(AgentRun.__table__)
        .values(job_id=job_id, kind=kind, started_at=now)
        .returning(AgentRun.__table__.c.id, AgentRun.__table__.c.started_at)
    )
    with engine.begin() as conn:
        row = conn.execute(stmt).one()
        return {"id": row.id, "job_id": job_id, "kind": kind, "started_at": row.started_at}


def get_latest_run(engine: Engine, job_id: int, kind: str = KIND_SCORE_FIT) -> dict | None:
    """The most recent run of `kind` for `job_id`, regardless of outcome
    (a caller that only wants successful runs should check
    `result["outcome"] == "success"` itself, or use
    get_latest_successful_result below). Returns None if this job has
    never had a run of this kind.

    This is the single query both real requirements resolve to: Slice 5's
    Job Agent gate ("has Score Fit run for job X") and the "user revisits a
    job, show the score without re-generating it" case - see the row's
    `outcome`/`result` to tell those apart.
    """
    stmt = (
        select(AgentRun.__table__)
        .where(AgentRun.__table__.c.job_id == job_id, AgentRun.__table__.c.kind == kind)
        .order_by(AgentRun.__table__.c.started_at.desc())
        .limit(1)
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().one_or_none()
        return dict(row) if row is not None else None


def get_latest_successful_result(
    engine: Engine, job_id: int, kind: str = KIND_SCORE_FIT
) -> dict | None:
    """The `result` JSONB (e.g. a FitAssessment.model_dump()) of the most
    recent *successful* run of `kind` for `job_id`, or None if no run of
    this kind has ever succeeded. This is what the API/UI reads to show a
    cached score on revisit without calling the agent again - deliberately
    not "most recent run regardless of outcome" (get_latest_run), since a
    failed run has no result worth showing.
    """
    stmt = (
        select(AgentRun.__table__.c.result)
        .where(
            AgentRun.__table__.c.job_id == job_id,
            AgentRun.__table__.c.kind == kind,
            AgentRun.__table__.c.outcome == "success",
        )
        .order_by(AgentRun.__table__.c.started_at.desc())
        .limit(1)
    )
    with engine.connect() as conn:
        result = conn.execute(stmt).scalar_one_or_none()
        return result


def end_run(
    engine: Engine,
    run_id: int,
    *,
    outcome: str,
    result: dict | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Close out a run once it finishes - successfully or not. `outcome` is
    a short status string ("success", "error: <message>"); `result` is the
    model's actual structured output (groundwork.agent.shared.schema.FitAssessment.
    model_dump()) on success, left None on error.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        update(AgentRun.__table__)
        .where(AgentRun.__table__.c.id == run_id)
        .values(
            ended_at=now,
            outcome=outcome,
            result=result,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def log_tool_call(engine: Engine, run_id: int, tool_name: str, args: dict, result: dict) -> dict:
    """Record one tool invocation against `run_id`. `args`/`result` must
    already be JSON-safe (no bare datetimes, etc.) - see
    groundwork.agent.tools for the helper that sanitizes tool output before
    it gets here.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(ToolCall.__table__)
        .values(run_id=run_id, tool_name=tool_name, args=args, result=result, created_at=now)
        .returning(ToolCall.__table__.c.id)
    )
    with engine.begin() as conn:
        row = conn.execute(stmt).one()
        return {"id": row.id, "run_id": run_id, "tool_name": tool_name}
