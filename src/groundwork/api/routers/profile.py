"""
/profile endpoints - BUILD_PLAN.md Slice 2: submit a resume as a PDF
upload, get back structured profile facts. Every submission is stored as a
new row (append-only history) - GET /profile returns the most recent one.

There was a raw-text POST /profile alongside the PDF upload route
originally - removed once PDF upload covered real usage and the raw-text
path had no user-facing purpose left (it stays useful as a direct call
into groundwork.extraction.extract_profile for tests/fixtures, which don't
need an HTTP route to do that).
"""

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel

from groundwork.db.engine import get_engine
from groundwork.db.profile import get_latest_profile, insert_profile
from groundwork.extraction.extract import extract_profile
from groundwork.extraction.pdf import extract_text_from_pdf
from groundwork.extraction.schema import ExtractedProfile

router = APIRouter(prefix="/profile", tags=["profile"])


def _extract_and_store(resume_text: str) -> ExtractedProfile:
    """Run extraction, persist the result as a new row, return it.
    Persisting the freshly-extracted object (not re-reading it back from
    the row insert_profile returns) is fine here - it's the same data
    either way, and skips a redundant round-trip.
    """
    profile = extract_profile(resume_text)
    insert_profile(get_engine(), profile.model_dump(mode="json"))
    return profile


@router.post(
    "/upload", response_model=ExtractedProfile, status_code=status.HTTP_201_CREATED
)
async def submit_profile_pdf(file: UploadFile) -> ExtractedProfile:
    """Submit a resume as an uploaded PDF; extract and persist it."""
    if file.content_type != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Expected a PDF (application/pdf), got {file.content_type!r}",
        )

    file_bytes = await file.read()

    try:
        resume_text = extract_text_from_pdf(file_bytes)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return _extract_and_store(resume_text)


@router.get("", response_model=ExtractedProfile)
def get_profile() -> ExtractedProfile:
    """Return the most recently submitted profile, or 404 if none exist yet."""
    row = get_latest_profile(get_engine())
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="no profile has been submitted yet"
        )
    return ExtractedProfile.model_validate(row["data"])
