"""Canonical tech job positions and their common title aliases/abbreviations.

Job postings use wildly inconsistent titles for the same underlying role -
SWE / SDE / "Software Engineer - Infrastructure" are all "Software
Engineer". This module is the single source of truth mapping a small,
fixed set of canonical positions to the aliases we've seen in the wild, so
filtering logic elsewhere doesn't special-case title strings itself.

Scope: tech roles only for now, per BUILD_PLAN Layer 1. This list will
never be complete - it just needs to grow as real postings don't match.
Once Layer 2's schema exists, CANONICAL_POSITIONS is the natural source for
a fixed "positions of interest" value a user selects from, rather than
free-text input.
"""

import re

# canonical position -> aliases/abbreviations that should count as a match.
# The canonical name itself is always an implicit alias.
CANONICAL_POSITIONS: dict[str, list[str]] = {
    "Software Engineer": [
        "swe",
        "sde",
        "software developer",
        "software development engineer",
        "sdet",
        "full stack engineer",
        "frontend engineer",
        "backend engineer",
    ],
    "AI Engineer": [
        "ai engineer",
        "ml engineer",
        "ai/ml engineer",
        "machine learning engineer",
        "applied scientist",
        "mle",
    ],
    "Computer Engineer": [
        "computer engineer",
        "hardware engineer",
        "embedded engineer",
    ],
    "Data Engineer": [
        "data engineer",
        "analytics engineer",
    ],
    "Forward Deployed Engineer": [
        "fde"
    ],
    "Solutions Engineer": [
        "SE"
    ]
}


def normalize_title(title: str) -> str:
    """Lowercase and collapse punctuation/whitespace for comparison.

    "Software Engineer - Infrastructure" -> "software engineer infrastructure"
    """
    normalized = title.lower() # lowercase
    normalized = re.sub(r"[^a-z0-9 ]", " ", normalized) # replace non alpha numeric values
    normalized = re.sub(r"\s+", " ", normalized).strip() # trialing whitespaces
    return normalized


def _word_boundary_pattern(phrase: str) -> re.Pattern:
    """Match `phrase` as whole words, not as a substring of something else.

    Without this, the alias "sde" would also match inside an unrelated
    word - it has to show up as its own token(s) in the title.
    """
    return re.compile(rf"\b{re.escape(phrase)}\b")


def matches_position(job_title: str, canonical_position: str) -> bool:
    """True if `job_title` should be considered an instance of `canonical_position`."""
    aliases = CANONICAL_POSITIONS.get(canonical_position, [])
    normalized_title = normalize_title(job_title) # normalize Job Title
    candidates = [normalize_title(canonical_position), *(normalize_title(a) for a in aliases)] # normalize title and aliases
    return any(_word_boundary_pattern(candidate).search(normalized_title) for candidate in candidates) # search job title for meatch


def filter_by_positions(jobs: list[dict], wanted_positions: list[str]) -> list[dict]:
    """Return only the jobs whose title matches one of `wanted_positions`.

    `wanted_positions` must be keys of CANONICAL_POSITIONS - this is a
    fixed selection, not free text, so a typo fails loudly instead of
    silently matching nothing.
    """
    unknown = set(wanted_positions) - set(CANONICAL_POSITIONS)
    if unknown:
        raise ValueError(f"unknown position(s): {sorted(unknown)}; choose from {sorted(CANONICAL_POSITIONS)}")

    return [
        job
        for job in jobs
        if any(matches_position(job["title"], position) for position in wanted_positions) # search job posting for postion matches
    ]
