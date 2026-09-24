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

`description` is stored as **Markdown**, not flattened plain text (see
html_to_text below) - it's still just a string column, still just as
LLM-readable (arguably more so - structure survives instead of getting
thrown away), and the frontend renders it with react-markdown rather than
dangerouslySetInnerHTML, so no raw HTML ever reaches the DOM. See UI.md
Step 4.
"""

import html
import re
from datetime import datetime, timezone

from markdownify import markdownify


def html_to_text(raw_html: str | None) -> str:
    """Turn escaped/raw HTML job content into Markdown.

    Plain get_text() (the previous approach here) ignores tag structure
    entirely - <h2>, <p>, and <li> boundaries all vanish, so a five-section
    posting collapses into one giant paragraph, and bold/heading emphasis
    is lost outright since there's no plain-text way to represent it.
    markdownify walks the same parsed tree but *keeps* that structure as
    Markdown syntax ("## heading", "**bold**", "- item") instead of
    discarding it - callers still run clean_whitespace() afterward to
    collapse the resulting runs of blank lines.
    """
    if not raw_html:
        return ""
    decoded = html.unescape(raw_html)
    return markdownify(decoded, heading_style="ATX")


def clean_whitespace(text: str | None) -> str:
    """Collapse repeated spaces/tabs and blank lines down to single ones.

    Leading whitespace on a line is left alone - Markdown uses it to mark a
    nested list item's continuation, so collapsing it there (as a blanket
    `re.sub(r"[ \t]+", " ", text)` over the whole string would) silently
    un-nests any sub-bullets a posting happens to have.
    """
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        leading = re.match(r"[ \t]*", line).group()
        rest = re.sub(r"[ \t]+", " ", line[len(leading):])
        lines.append(leading + rest)
    text = "\n".join(lines)
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
