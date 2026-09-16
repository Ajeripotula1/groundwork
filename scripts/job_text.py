"""Shared helpers for turning each ATS's raw job payload into one consistent,
human/LLM-readable posting - and one consistent dict shape - across
Greenhouse, Ashby, and Lever.

Each ATS buries the description/requirements/skills text differently:
  - Greenhouse: one `content` field, HTML.
  - Ashby: one `descriptionPlain` field, already plain text.
  - Lever: split across `descriptionPlain` (intro) and a `lists` array of
    {text: heading, content: HTML} sections - requirements/skills live in
    `lists`, not in the description field.

Centralizing the cleanup here (instead of copy-pasting BeautifulSoup calls
into three scripts) is what makes the three explore_*.py scripts produce the
literal same normalized shape - the input Slice 1's `jobs` table gets
designed around, per BUILD_PLAN.md.
"""

import html
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup


def html_to_text(raw_html: str | None) -> str:
    """Turn escaped/raw HTML job content into plain, readable text."""
    if not raw_html:
        return ""
    decoded = html.unescape(raw_html)
    soup = BeautifulSoup(decoded, "html.parser")
    return soup.get_text(" ", strip=True)


def clean_whitespace(text: str | None) -> str:
    """Collapse repeated spaces/tabs and blank lines down to single ones."""
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def normalized_job(
    *,
    ats_job_id: str,
    source: str,
    board_token: str,
    title: str,
    description: str,
    url: str | None,
    raw: dict,
) -> dict:
    """Build the one job shape shared by all three ATS scripts.

    `raw` should be the untouched API payload for this posting (not a
    mutated copy) - it's kept in full precisely because the schema isn't
    locked in yet; anything we didn't think to pull out explicitly is
    still recoverable from here.
    """
    return {
        "ats_job_id": str(ats_job_id),
        "source": source,
        "board_token": board_token,
        "title": title,
        "description": clean_whitespace(description) or "Unable to parse description",
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw_json": raw,
    }


def summarize_jobs(label: str, jobs: list[dict], filtered: bool) -> None:
    """Print a normalized job list - shared across all three explore scripts."""
    kind = "matching jobs" if filtered else "jobs"
    print(f"\n=== {label}: {len(jobs)} {kind} ===")
    if not jobs:
        return

    for job in jobs[:20]:
        preview = job["description"][:150].replace("\n", " ")
        print(f"  - [{job['ats_job_id']}] {job['title']!r}")
        print(f"      url: {job['url']}")
        print(f"      description preview: {preview}...")
