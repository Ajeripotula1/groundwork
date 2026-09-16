"""Pull a company's public Ashby job board and produce normalized,
LLM/human-readable job postings.

This is exploration for BUILD_PLAN.md Slice 1 (job data the agent can
read): still no database, but the output here - via job_text.normalized_job
- is exactly the shape Slice 1's `jobs` table gets designed around, and it's
the same shape explore_greenhouse.py and explore_lever.py produce.

Ashby is the easy case of the three: `descriptionPlain` already holds the
full posting (intro + requirements + skills) as plain text, no HTML
stripping and no digging into a separate section list like Lever needs.

Usage:
    python scripts/explore_asby.py <board_token> [<board_token> ...]
    python scripts/explore_asby.py ramp --positions "Software Engineer"

The board token is the slug in a company's public board URL - e.g. for
jobs.ashbyhq.com/ramp the token is "ramp".
"""

import argparse

import requests

from job_text import normalized_job, summarize_jobs
from positions import CANONICAL_POSITIONS, filter_by_positions

ASHBY_BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def fetch_jobs(board_token: str) -> list[dict]:
    """Fetch every posting on a company's Ashby job board, normalized."""
    url = ASHBY_BOARD_URL.format(token=board_token)
    try:
        response = requests.get(url, timeout=10)
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("request timed out - Ashby might be slow/down") from exc
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError("network error - check your connection/DNS") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"unexpected request error: {exc}") from exc

    if response.status_code == 404:
        raise RuntimeError(f"job board not found for '{board_token}' - check the token is correct")
    if response.status_code != 200:
        raise RuntimeError(f"Ashby returned HTTP {response.status_code}")

    jobs = []
    for job in response.json().get("jobs", []):
        description = job.get("descriptionPlain")
        if not description:
            continue
        jobs.append(
            normalized_job(
                ats_job_id=job["id"],
                source="ashby",
                board_token=board_token,
                title=job["title"],
                description=description,
                url=job.get("jobUrl"),
                raw=job,
            )
        )
    print(jobs[0]['description'])
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board_tokens", nargs="+", help="Ashby board token(s), e.g. 'ramp'")
    parser.add_argument(
        "--positions",
        nargs="+",
        choices=sorted(CANONICAL_POSITIONS),
        help="Only show jobs matching these canonical positions (title-variance aware)",
    )
    args = parser.parse_args()

    for board_token in args.board_tokens:
        try:
            jobs = fetch_jobs(board_token)
        except RuntimeError as exc:
            print(f"skipping '{board_token}': {exc}")
            continue

        if args.positions:
            jobs = filter_by_positions(jobs, args.positions)
        summarize_jobs(board_token, jobs, filtered=bool(args.positions))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
