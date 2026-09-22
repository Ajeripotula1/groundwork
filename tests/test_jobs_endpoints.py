"""
Unit tests for the /jobs router (BUILD_PLAN.md Slice 6): job list/detail,
Score Fit trigger/read, and the pre-existing Job Agent turn endpoints.

Same approach as tests/test_profile_endpoint.py: every DB/agent call is
mocked (monkeypatched on the names as imported into
jobsentinel.api.routers.jobs), so this suite is fast/free/deterministic and
needs no real Postgres or Bedrock. Real behavior (an actual Score Fit run,
actual Job Agent memory recall) was verified manually against local
Postgres/Bedrock earlier - these tests only check the routers' own wiring:
request/response shape, status codes, which underlying function got called
with what.
"""

import pytest
from fastapi.testclient import TestClient

from jobsentinel.agent.shared.schema import FitAssessment, Match
from jobsentinel.api.auth import get_current_user_id
from jobsentinel.api.main import app

client = TestClient(app)

TEST_USER_ID = "user_test123"


@pytest.fixture(autouse=True)
def fake_auth():
    """The score/agent routes below require sign-in - override the
    dependency for the whole suite, same reasoning as
    tests/test_profile_endpoint.py's fake_auth. GET /jobs and GET
    /jobs/{id} don't depend on it at all (job-board data is public), so
    this is harmless overhead for those tests, not a requirement."""
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    yield
    del app.dependency_overrides[get_current_user_id]


def _fake_assessment() -> dict:
    return FitAssessment(
        summary="Solid overlap on backend fundamentals, thin on seniority.",
        strengths=[],
        gaps=[],
        match=Match.WEAK_MATCH,
        recommendation_note="Emphasize any large-scale system work you have.",
    ).model_dump(mode="json")


# ---- GET /jobs ----------------------------------------------------------


def test_list_all_jobs_returns_summaries(monkeypatch):
    fake_job = {
        "id": 182,
        "title": "Full-Stack Software Engineer, RL",
        "source": "greenhouse",
        "board_token": "anthropic",
        "url": "https://example.com/182",
        "fetched_at": "2026-01-01T00:00:00Z",
    }
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.list_jobs", lambda engine: [fake_job]
    )

    response = client.get("/jobs")

    assert response.status_code == 200
    body = response.json()
    assert body == [fake_job]
    # Summary shape only - no description/raw_json leaking through.
    assert "description" not in body[0]


# ---- GET /jobs/{id} -------------------------------------------------------


def test_read_job_returns_detail(monkeypatch):
    fake_job = {
        "id": 182,
        "ats_job_id": "5186067008",
        "title": "Full-Stack Software Engineer, RL",
        "description": "Full posting text...",
        "source": "greenhouse",
        "board_token": "anthropic",
        "url": "https://example.com/182",
        "raw_json": {"anything": "here"},
        "fetched_at": "2026-01-01T00:00:00Z",
    }
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: fake_job
    )

    response = client.get("/jobs/182")

    assert response.status_code == 200
    assert response.json()["description"] == "Full posting text..."


def test_read_job_404s_when_missing(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: None
    )

    response = client.get("/jobs/999999")

    assert response.status_code == 404


# ---- POST /jobs/{id}/score ------------------------------------------------


def test_run_score_fit_returns_assessment(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.invoke_score_fit",
        lambda payload: _fake_assessment(),
    )

    response = client.post("/jobs/182/score", json={})

    assert response.status_code == 200
    assert response.json()["match"] == "weak_match"


def test_run_score_fit_returns_422_on_agent_error(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.invoke_score_fit",
        lambda payload: {"error": "no profile has been submitted yet"},
    )

    response = client.post("/jobs/182/score", json={})

    assert response.status_code == 422


def test_run_score_fit_404s_when_job_missing(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: None
    )

    response = client.post("/jobs/999999/score", json={})

    assert response.status_code == 404


# ---- GET /jobs/{id}/score ---------------------------------------------------


def test_read_score_fit_returns_cached_result(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_latest_profile", lambda engine, user_id: {"id": 3}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_latest_successful_result",
        lambda engine, job_id, kind, profile_id: _fake_assessment(),
    )

    response = client.get("/jobs/182/score")

    assert response.status_code == 200
    assert response.json()["match"] == "weak_match"


def test_read_score_fit_404s_when_never_scored(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_latest_profile", lambda engine, user_id: {"id": 3}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_latest_successful_result",
        lambda engine, job_id, kind, profile_id: None,
    )

    response = client.get("/jobs/182/score")

    assert response.status_code == 404


def test_read_score_fit_with_explicit_profile_id(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_profile", lambda engine, profile_id, user_id: {"id": profile_id}
    )
    seen_profile_ids = []
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_latest_successful_result",
        lambda engine, job_id, kind, profile_id: seen_profile_ids.append(profile_id)
        or _fake_assessment(),
    )

    response = client.get("/jobs/182/score", params={"profile_id": 1})

    assert response.status_code == 200
    assert seen_profile_ids == [1]


def test_read_score_fit_unknown_profile_id_404s(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_profile", lambda engine, profile_id, user_id: None
    )

    response = client.get("/jobs/182/score", params={"profile_id": 999})

    assert response.status_code == 404


# ---- Job Agent turn endpoints (pre-existing, previously untested) --------


def test_continue_job_agent_returns_reply(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.invoke_job_agent",
        lambda payload: {"reply": "Let's start with your most recent role."},
    )

    response = client.post("/jobs/182/agent", json={"message": "help me tailor my resume"})

    assert response.status_code == 200
    assert response.json() == {"reply": "Let's start with your most recent role."}


def test_read_job_agent_history_returns_transcript(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    # No profile_id given -> read_job_agent_history resolves "latest",
    # same as continue_job_agent's invoke() does, so the two agree on which
    # (job_id, profile_id) session to read/write - see job_session_id.
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_latest_profile", lambda engine, user_id: {"id": 3}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.list_conversation",
        lambda actor_id, session_id: [{"role": "user", "text": "hi"}],
    )

    response = client.get("/jobs/182/agent")

    assert response.status_code == 200
    assert response.json() == [{"role": "user", "text": "hi"}]


def test_read_job_agent_history_with_explicit_profile_id(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_profile", lambda engine, profile_id, user_id: {"id": profile_id}
    )
    seen_session_ids = []
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.list_conversation",
        lambda actor_id, session_id: seen_session_ids.append(session_id) or [],
    )

    response = client.get("/jobs/182/agent", params={"profile_id": 3})

    assert response.status_code == 200
    assert seen_session_ids == ["job-182-profile-3"]


def test_read_job_agent_history_unknown_profile_id_404s(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_job", lambda engine, job_id: {"id": job_id}
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.jobs.get_profile", lambda engine, profile_id, user_id: None
    )

    response = client.get("/jobs/182/agent", params={"profile_id": 999})

    assert response.status_code == 404
