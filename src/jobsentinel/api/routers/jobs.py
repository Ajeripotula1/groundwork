"""
/jobs endpoints - BUILD_PLAN.md Slice 6: list/view the jobs already loaded
into Postgres, trigger or read a Score Fit assessment, and start/continue
a Job Agent turn + fetch its conversation history. Everything a frontend
needs for list -> view -> score -> (if scored) talk to the Job Agent ->
see history - no more, per this slice's explicit scope-down.

Calls straight into jobsentinel.agent.{score_fit,job_agent}.agent.invoke()
- in-process function calls, never a network hop to a deployed AgentCore
Runtime. Per api/main.py's docstring on the hard architectural rule, this
app never calls Bedrock itself; it only calls into jobsentinel.agent's
public functions, which do that internally.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from jobsentinel.agent.job_agent.agent import invoke as invoke_job_agent
from jobsentinel.agent.score_fit.agent import invoke as invoke_score_fit
from jobsentinel.agent.shared.memory import job_session_id, list_conversation
from jobsentinel.api.auth import get_current_user_id
from jobsentinel.agent.shared.schema import FitAssessment
from jobsentinel.db.agent_runs import KIND_SCORE_FIT, get_latest_successful_result
from jobsentinel.db.engine import get_engine
from jobsentinel.db.jobs import get_job, list_jobs
from jobsentinel.db.profile import get_latest_profile, get_profile

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobAgentTurnRequest(BaseModel):
    message: str = Field(min_length=1)
    # See job_agent.agent.build_tools' docstring for why this is a
    # client-supplied override rather than always "the latest profile".
    profile_id: int | None = None


class JobAgentTurnResponse(BaseModel):
    reply: str


class JobAgentTurn(BaseModel):
    role: str
    text: str


class JobSummary(BaseModel):
    id: int
    title: str
    source: str
    board_token: str
    url: str | None
    fetched_at: datetime


class JobDetail(JobSummary):
    ats_job_id: str
    description: str


class ScoreFitRequest(BaseModel):
    # See job_agent.agent.build_tools' docstring for why this is a
    # client-supplied override rather than always "the latest profile".
    profile_id: int | None = None


def _require_job(job_id: int) -> None:
    if get_job(get_engine(), job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job with id {job_id}")

#### Retrieve all or specific Jobs ####
@router.get("", response_model=list[JobSummary])
def list_all_jobs() -> list[JobSummary]:
    """Every job currently loaded, summary fields only - see
    db.jobs.list_jobs's docstring for why there's no pagination/filtering
    yet."""
    return [JobSummary(**job) for job in list_jobs(get_engine())]


@router.get("/{job_id}", response_model=JobDetail)
def read_job(job_id: int) -> JobDetail:
    """Full detail for one job, including its description."""
    job = get_job(get_engine(), job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job with id {job_id}")
    return JobDetail(**job)

#### Score Fit Agent generate new score or retreieve latest score for specific job ####
@router.post("/{job_id}/score", response_model=FitAssessment)
def run_score_fit(
    job_id: int,
    body: ScoreFitRequest | None = None,
    current_user_id: str = Depends(get_current_user_id),
) -> FitAssessment:
    """Trigger a fresh Score Fit run for this job - always re-runs, never
    serves a cached result (GET below does that). Mirrors
    continue_job_agent's in-process invoke() pattern.

    A 404 here means the job itself doesn't exist. invoke_score_fit's own
    "no profile submitted yet" / "no profile with that id" errors map to
    422 instead - the job exists, so it's a client-input problem, the same
    status profile.py uses for an unprocessable PDF.
    """
    _require_job(job_id)
    profile_id = body.profile_id if body else None
    result = invoke_score_fit(
        {"job_id": job_id, "user_id": current_user_id, "profile_id": profile_id}
    )
    if "error" in result:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=result["error"])
    return FitAssessment.model_validate(result)


@router.get("/{job_id}/score", response_model=FitAssessment)
def read_score_fit(
    job_id: int,
    profile_id: int | None = None,
    current_user_id: str = Depends(get_current_user_id),
) -> FitAssessment:
    """The latest successful stored Score Fit result for this job against
    `profile_id` (or the latest profile, if omitted), without re-running -
    404 if that (job, profile) pair has never been scored successfully.

    Resolves `profile_id` the same way run_score_fit/invoke_job_agent do
    (an explicit id if given, else the latest profile) so this reads back
    the same run a client that just POSTed with the same profile_id would
    see - see get_latest_successful_result's profile_id filter in
    jobsentinel.db.agent_runs for why this can't just be "latest run for
    this job" once a job's been scored against more than one profile.

    `profile_id` here is client-supplied (a query param), so get_profile is
    called with `current_user_id` to enforce ownership - see get_profile's
    docstring; a mismatch reads back as the same 404 an unknown id gets.
    """
    _require_job(job_id)
    engine = get_engine()
    if profile_id is not None:
        if get_profile(engine, profile_id, current_user_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no profile with id {profile_id}")
    else:
        profile = get_latest_profile(engine, current_user_id)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no profile has been submitted yet")
        profile_id = profile["id"]
    result = get_latest_successful_result(engine, job_id, kind=KIND_SCORE_FIT, profile_id=profile_id)
    if result is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="no Score Fit result yet for this job/profile"
        )
    return FitAssessment.model_validate(result)


@router.post("/{job_id}/agent", response_model=JobAgentTurnResponse)
def continue_job_agent(
    job_id: int,
    body: JobAgentTurnRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> JobAgentTurnResponse:
    """Send one message to the Job Agent for this job and return its reply.

    A 404 here only means the job itself doesn't exist. invoke()'s own
    "no successful Score Fit run yet" gate returns its message as a
    conversational `reply` (see that function's docstring), not an HTTP
    error - it's meant to be shown to the user like any other agent
    message, not handled as a distinct API error case.
    """
    _require_job(job_id)
    result = invoke_job_agent(
        {
            "job_id": job_id,
            "user_id": current_user_id,
            "message": body.message,
            "profile_id": body.profile_id,
        }
    )
    return JobAgentTurnResponse(reply=result.get("reply") or result["error"])


@router.get("/{job_id}/agent", response_model=list[JobAgentTurn])
def read_job_agent_history(
    job_id: int,
    profile_id: int | None = None,
    current_user_id: str = Depends(get_current_user_id),
) -> list[JobAgentTurn]:
    """Return this job's Job Agent conversation so far, oldest first.

    A conversation is scoped to (job_id, profile_id) - see job_session_id's
    docstring - so this must resolve the same concrete profile_id
    continue_job_agent's invoke() call did, the same way it did (an
    explicit id if given, else the latest profile), or it would read back
    a different, empty session than the one that turn actually wrote to.

    `profile_id` here is client-supplied (a query param), so get_profile is
    called with `current_user_id` to enforce ownership, same as
    read_score_fit above - a mismatch reads back as the same 404 an unknown
    id gets, and actor_id=current_user_id below (not a shared constant)
    is what actually keeps this read scoped to the caller's own
    conversation - see jobsentinel.agent.shared.memory's docstring on why
    session_id alone isn't unique across users.
    """
    _require_job(job_id)
    if profile_id is not None:
        if get_profile(get_engine(), profile_id, current_user_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no profile with id {profile_id}")
    else:
        profile = get_latest_profile(get_engine(), current_user_id)
        if profile is None:
            return []
        profile_id = profile["id"]
    transcript = list_conversation(
        actor_id=current_user_id, session_id=job_session_id(job_id, profile_id)
    )
    return [JobAgentTurn(**turn) for turn in transcript]
