"""
Test for the resume-extraction utility itself (BUILD_PLAN.md Slice 2).

Unlike tests/test_profile_endpoint.py - which mocks extract_profile out
entirely to test the API's wiring - this hits real Bedrock. It's the one
test that actually checks the model's output is sane, not just that the
right function gets called with the right argument.

Marked `integration`: costs real Bedrock tokens, is slower, and the model's
exact output isn't deterministic run to run - every assertion below is
loose (content-level: "the skills list contains Python") rather than
exact-match, and the fixture resume never changes, so a failure here means
either the extraction prompt broke or genuinely hallucinated - not fixture
drift.
"""

from pathlib import Path

import pytest

from jobsentinel.extraction.extract import extract_profile

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.integration
def test_extract_profile_against_real_bedrock():
    resume_text = (FIXTURES_DIR / "sample_resume.txt").read_text()

    profile = extract_profile(resume_text)

    # Contact info is near-verbatim - should extract essentially exactly.
    assert profile.contact.name == "Jane Doe"
    assert profile.contact.email == "jane.doe@email.com"

    # Content-level checks on each section - not exact-match, since the
    # model's exact phrasing/casing/ordering can vary between runs.
    assert any("berkeley" in edu.institution.lower() for edu in profile.education)
    assert any("acme corp" in exp.company.lower() for exp in profile.experience)
    assert any(
        "finance tracker" in project.name.lower() for project in profile.projects
    )
    assert any(
        "aws certified" in cert.name.lower() for cert in profile.certifications
    )
    assert any("python" in skill.lower() for skill in profile.skills)

    # The actual anti-hallucination check, not just a shape check: this
    # fixture resume has no summary/objective statement, so the model must
    # leave the field empty rather than composing one itself.
    assert profile.summary is None
