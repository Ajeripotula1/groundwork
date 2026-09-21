"""
Unit tests for POST /profile/upload and GET /profile (BUILD_PLAN.md
Slice 2).

These mock out extract_profile AND the DB layer (insert_profile/
get_latest_profile) - they test the endpoints' wiring (request validation,
response shape, status codes, PDF handling), not the LLM's extraction
quality or real persistence. Both of those are deliberately separate
concerns: a test hitting real Bedrock is tests/test_extract_profile.py
(loose assertions against non-deterministic output, not exact-match), and
real persistence was verified manually against local Postgres (same as
Slice 1's jobs loader - no automated DB-layer tests exist for that either
yet). Here, CI needs something fast, free, and deterministic - no running
Postgres required.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobsentinel.api.auth import get_current_user_id
from jobsentinel.api.main import app
from jobsentinel.extraction.schema import ContactInfo, ExtractedProfile, WorkExperience

client = TestClient(app)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

TEST_USER_ID = "user_test123"


@pytest.fixture(autouse=True)
def fake_auth():
    """Every route in this file requires sign-in (Depends(get_current_user_id))
    - override it for the whole suite so tests exercise the routes' own
    logic, not Clerk's JWT verification (that's tests/test_auth.py's job).
    Same "mock the external boundary" pattern as mock_insert_profile below.
    """
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    yield
    del app.dependency_overrides[get_current_user_id]


@pytest.fixture(autouse=True)
def mock_insert_profile(monkeypatch):
    """Every submit test in this file goes through _extract_and_store,
    which calls insert_profile - mocked for every test here so persistence
    never depends on a real Postgres being up."""
    monkeypatch.setattr(
        "jobsentinel.api.routers.profile.insert_profile",
        lambda engine, data, user_id: None,
    )


def _fake_profile() -> ExtractedProfile:
    return ExtractedProfile(
        contact=ContactInfo(name="Jane Doe", email="jane@example.com"),
        experience=[
            WorkExperience(
                company="Acme Corp",
                title="Software Engineer",
                bullets=["Built a REST API using FastAPI"],
            )
        ],
        skills=["Python", "FastAPI"],
    )


def test_submit_profile_pdf_inserts_a_new_row_each_time(monkeypatch):
    # Append-only history: two submissions should be two separate inserts,
    # never an update to the same row.
    calls = []
    monkeypatch.setattr(
        "jobsentinel.api.routers.profile.extract_profile", lambda t: _fake_profile()
    )
    monkeypatch.setattr(
        "jobsentinel.api.routers.profile.insert_profile",
        lambda engine, data, user_id: calls.append(data),
    )

    pdf_bytes = (FIXTURES_DIR / "sample_resume.pdf").read_bytes()
    for _ in range(2):
        client.post(
            "/profile/upload",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
        )

    assert len(calls) == 2


def test_get_profile_returns_profile_by_id(monkeypatch):
    stored = _fake_profile().model_dump(mode="json")
    monkeypatch.setattr(
        "jobsentinel.api.routers.profile.get_profile",
        lambda engine, id, user_id: {"id": id, "data": stored, "created_at": None},
    )

    response = client.get("/profile", params={"id": 2})

    assert response.status_code == 200
    assert response.json()["contact"]["name"] == "Jane Doe"


def test_get_profile_returns_404_when_id_not_found(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.profile.get_profile", lambda engine, id, user_id: None
    )

    response = client.get("/profile", params={"id": 999})

    assert response.status_code == 404


def test_get_profile_without_id_returns_latest_profile(monkeypatch):
    stored = _fake_profile().model_dump(mode="json")
    calls = []

    def fake_get_latest_profile(engine, user_id):
        calls.append(user_id)
        return {"id": 7, "data": stored, "created_at": None}

    monkeypatch.setattr(
        "jobsentinel.api.routers.profile.get_latest_profile", fake_get_latest_profile
    )

    response = client.get("/profile")

    assert response.status_code == 200
    assert response.json()["contact"]["name"] == "Jane Doe"
    assert calls == [TEST_USER_ID]


def test_get_profile_without_id_returns_404_when_never_submitted(monkeypatch):
    monkeypatch.setattr(
        "jobsentinel.api.routers.profile.get_latest_profile", lambda engine, user_id: None
    )

    response = client.get("/profile")

    assert response.status_code == 404
    assert response.json()["detail"] == "no profile has been submitted yet"


def test_submit_profile_pdf_extracts_text_and_returns_profile(monkeypatch):
    received = {}

    def fake_extract(resume_text: str) -> ExtractedProfile:
        received["resume_text"] = resume_text
        return _fake_profile()

    monkeypatch.setattr("jobsentinel.api.routers.profile.extract_profile", fake_extract)

    pdf_bytes = (FIXTURES_DIR / "sample_resume.pdf").read_bytes()
    response = client.post(
        "/profile/upload",
        files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["contact"]["name"] == "Jane Doe"
    # The real PdfReader ran (not mocked) - confirms text actually made it
    # out of the PDF and through to the extractor, not just an empty string.
    assert "Jane Doe" in received["resume_text"]
    assert "Software Engineer" in received["resume_text"]


def test_submit_profile_pdf_rejects_non_pdf_content_type():
    response = client.post(
        "/profile/upload",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )

    assert response.status_code == 415


def test_submit_profile_pdf_rejects_unreadable_pdf():
    response = client.post(
        "/profile/upload",
        files={"file": ("resume.pdf", b"not actually a pdf", "application/pdf")},
    )

    assert response.status_code == 422