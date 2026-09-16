"""Pull a company's public Lever postings and produce normalized,
LLM/human-readable job postings.

This is exploration for BUILD_PLAN.md Slice 1 (job data the agent can
read): still no database, but the output here - via job_text.normalized_job
- is exactly the shape Slice 1's `jobs` table gets designed around, and it's
the same shape explore_greenhouse.py and explore_asby.py produce.

Lever is the hard case of the three. Two structural quirks:
  - the endpoint returns a bare JSON array, not a dict with a "jobs" key
  - the description is fragmented: `descriptionPlain` is only the intro,
    and the actual requirements/skills live in `lists` - an array of
    {text: heading, content: HTML} sections (e.g. "What you'll do",
    "What you need"). Joining descriptionPlain with each list's cleaned
    content is what makes the result usable.

Usage:
    python scripts/explore_lever.py <company> [<company> ...]
    python scripts/explore_lever.py leverdemo --positions "Software Engineer"

The company slug is what appears in jobs.lever.co/<company>.
"""

import argparse

import requests

from job_text import clean_whitespace, html_to_text, normalized_job, summarize_jobs
from positions import CANONICAL_POSITIONS, filter_by_positions

LEVER_POSTINGS_URL = "https://api.lever.co/v0/postings/{company}?mode=json"


def _combine_description(job: dict) -> str:
    """Join Lever's intro text with each `lists` section into one block.

    Each list item is {"text": <heading>, "content": <HTML>} - the heading
    is kept as a label so requirements/skills sections stay identifiable
    instead of blurring into one undifferentiated paragraph.
    """
    parts = []

    intro = job.get("descriptionPlain")
    if intro:
        parts.append(intro)

    for section in job.get("lists", []):
        heading = (section.get("text") or "").strip()
        body = html_to_text(section.get("content"))
        if not body:
            continue
        parts.append(f"{heading}:\n{body}" if heading else body)

    additional = job.get("additionalPlain")
    if additional:
        parts.append(additional)

    return "\n\n".join(parts)


def fetch_jobs(company: str) -> list[dict]:
    """Fetch every posting for a company on Lever, normalized."""
    url = LEVER_POSTINGS_URL.format(company=company)
    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("request timed out - Lever might be slow/down") from exc
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError("network error - check your connection/DNS") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"unexpected request error: {exc}") from exc

    if response.status_code == 404:
        raise RuntimeError(f"postings not found for '{company}' - check the slug is correct")
    if response.status_code != 200:
        raise RuntimeError(f"Lever returned HTTP {response.status_code}")

    jobs = []
    for job in response.json():
        description = clean_whitespace(_combine_description(job))
        if not description:
            continue
        jobs.append(
            normalized_job(
                ats_job_id=job["id"],
                source="lever",
                board_token=company,
                # Lever's title field is "text", not "title" - kept as a
                # local variable here rather than mutating `job` itself, so
                # `raw` below stays the untouched original API response.
                title=job.get("text", ""),
                description=description,
                url=job.get("hostedUrl"),
                raw=job,
            )
        )
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("companies", nargs="+", help="Lever company slug(s), e.g. 'leverdemo'")
    parser.add_argument(
        "--positions",
        nargs="+",
        choices=sorted(CANONICAL_POSITIONS),
        help="Only show jobs matching these canonical positions (title-variance aware)",
    )
    args = parser.parse_args()

    for company in args.companies:
        try:
            jobs = fetch_jobs(company)
        except RuntimeError as exc:
            print(f"skipping '{company}': {exc}")
            continue

        if args.positions:
            jobs = filter_by_positions(jobs, args.positions)
        summarize_jobs(company, jobs, filtered=bool(args.positions))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
