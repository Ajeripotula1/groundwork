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

from groundwork.api.main import app
from groundwork.extraction.schema import ContactInfo, ExtractedProfile, WorkExperience

client = TestClient(app)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def mock_insert_profile(monkeypatch):
    """Every submit test in this file goes through _extract_and_store,
    which calls insert_profile - mocked for every test here so persistence
    never depends on a real Postgres being up."""
    monkeypatch.setattr(
        "groundwork.api.routers.profile.insert_profile",
        lambda engine, data: None,
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
        "groundwork.api.routers.profile.extract_profile", lambda t: _fake_profile()
    )
    monkeypatch.setattr(
        "groundwork.api.routers.profile.insert_profile",
        lambda engine, data: calls.append(data),
    )

    pdf_bytes = (FIXTURES_DIR / "sample_resume.pdf").read_bytes()
    for _ in range(2):
        client.post(
            "/profile/upload",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
        )

    assert len(calls) == 2


def test_get_profile_returns_latest_profile(monkeypatch):
    stored = _fake_profile().model_dump(mode="json")
    monkeypatch.setattr(
        "groundwork.api.routers.profile.get_latest_profile",
        lambda engine: {"id": 2, "data": stored, "created_at": None},
    )

    response = client.get("/profile")

    assert response.status_code == 200
    assert response.json()["contact"]["name"] == "Jane Doe"


def test_get_profile_returns_404_when_nothing_stored(monkeypatch):
    monkeypatch.setattr(
        "groundwork.api.routers.profile.get_latest_profile", lambda engine: None
    )

    response = client.get("/profile")

    assert response.status_code == 404


def test_submit_profile_pdf_extracts_text_and_returns_profile(monkeypatch):
    received = {}

    def fake_extract(resume_text: str) -> ExtractedProfile:
        received["resume_text"] = resume_text
        return _fake_profile()

    monkeypatch.setattr("groundwork.api.routers.profile.extract_profile", fake_extract)

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