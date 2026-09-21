"""Pydantic schema for the resume-extraction utility (BUILD_PLAN.md Slice 2).

Resume text in, ExtractedProfile out.

Design rule threaded through every field below: nothing is required except
whatever makes an entry identifiable (a company, an institution, a name).
Everything else is Optional or defaults to an empty list/collection. A resume
with no Certifications section should produce certifications=[], never a
fabricated entry - required fields are exactly what pressure a model into
inventing something to fill them.
"""

from pydantic import BaseModel, Field


class ContactInfo(BaseModel):
    """Identifying info, usually copied near-verbatim from the resume header.

    Low hallucination risk relative to the rest of the profile - this is
    literal text on the page, not something the model has to summarize or
    judge. Still all Optional: a resume fragment (or a bad PDF-to-text pass,
    once file upload exists) may be missing any of these.
    """

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str | None = None
    location: str | None = None
    dates: str | None = None
    # Optional line items: GPA, honors, relevant coursework - whatever's
    # actually present. Not a place to infer anything not stated.
    details: list[str] = Field(default_factory=list)


class WorkExperience(BaseModel):
    company: str
    title: str
    location: str | None = None
    dates: str | None = None
    # One string per bullet point, kept close to the source line. This is
    # what makes hallucination auditable later (Slice 4's eval wants to
    # check the agent never cites something not in the profile) - a single
    # blob paragraph loses that traceability.
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    dates: str | None = None
    # Same bullet-per-line reasoning as WorkExperience.
    bullets: list[str] = Field(default_factory=list)
    # Only populated if the resume explicitly names a stack for this
    # project - never inferred from the description text.
    technologies: list[str] = Field(default_factory=list)
    url: str | None = None


class Certification(BaseModel):
    name: str
    issuer: str | None = None
    # Free text, not a date - certifications are often written as
    # "Issued Jun 2023" or "2023 - 2026" (with an expiry).
    date: str | None = None


class ExtractedProfile(BaseModel):
    """Full structured snapshot the extraction utility returns for one resume."""

    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str | None = None
    education: list[Education] = Field(default_factory=list)
    experience: list[WorkExperience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)