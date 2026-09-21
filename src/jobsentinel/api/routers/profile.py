"""
/profile endpoints - BUILD_PLAN.md Slice 2: submit a resume as a PDF
upload, get back structured profile facts. Every submission is stored as a
new row (append-only history) - GET /profile returns the most recent one.

There was a raw-text POST /profile alongside the PDF upload route
originally - removed once PDF upload covered real usage and the raw-text
path had no user-facing purpose left (it stays useful as a direct call
into jobsentinel.extraction.extract_profile for tests/fixtures, which don't
need an HTTP route to do that).
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel

from jobsentinel.api.auth import get_current_user_id
from jobsentinel.db.engine import get_engine
from jobsentinel.db.profile import get_latest_profile, get_profile, insert_profile
from jobsentinel.extraction.extract import extract_profile
from jobsentinel.extraction.pdf import extract_text_from_pdf
from jobsentinel.extraction.schema import ExtractedProfile

router = APIRouter(prefix="/profile", tags=["profile"])


def _extract_and_store(resume_text: str, user_id: str) -> ExtractedProfile:
    """Run extraction, persist the result as a new row owned by `user_id`,
    return it. Persisting the freshly-extracted object (not re-reading it
    back from the row insert_profile returns) is fine here - it's the same
    data either way, and skips a redundant round-trip.
    """
    profile = extract_profile(resume_text)
    insert_profile(get_engine(), profile.model_dump(mode="json"), user_id)
    return profile


@router.post(
    "/upload", response_model=ExtractedProfile, status_code=status.HTTP_201_CREATED
)
async def submit_profile_pdf(
    file: UploadFile, current_user_id: str = Depends(get_current_user_id)
) -> ExtractedProfile:
    """Submit a resume as an uploaded PDF; extract and persist it under the
    signed-in user."""
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

    return _extract_and_store(resume_text, current_user_id)


@router.get("", response_model=ExtractedProfile)
def read_profile(
    id: int | None = None, current_user_id: str = Depends(get_current_user_id)
) -> ExtractedProfile:
    """Return a profile snapshot for the signed-in caller.

    With `id`, returns that specific historical snapshot, or 404 if it
    doesn't exist or belongs to a different user - see get_profile's
    docstring on why a mismatch reads back as "not found" rather than a
    403. Without `id`, returns the caller's most recent submission (or 404
    if they've never submitted one) - this is what lets a client ask "what
    profile does this user currently have" on first load without already
    knowing a profile_id, the same "most recent row is the current one"
    resolution get_latest_profile already does for the agents.
    """
    engine = get_engine()
    if id is not None:
        row = get_profile(engine, id, current_user_id)
        not_found_detail = "no profile with that id"
    else:
        row = get_latest_profile(engine, current_user_id)
        not_found_detail = "no profile has been submitted yet"
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=not_found_detail)
    return ExtractedProfile.model_validate(row["data"])
