"""Pull a company's public Greenhouse job board and produce normalized,
LLM/human-readable job postings.

This is exploration for BUILD_PLAN.md Slice 1 (job data the agent can
read): still no database, but the output here - via job_text.normalized_job
- is exactly the shape Slice 1's `jobs` table gets designed around.

Usage:
    python scripts/explore_greenhouse.py <board_token> [<board_token> ...]
    python scripts/explore_greenhouse.py anthropic --positions "Software Engineer" "AI Engineer"

The board token is the slug in a company's public board URL - e.g. for
boards.greenhouse.io/anthropic the token is "anthropic".
"""

import argparse

import requests

from job_text import html_to_text, normalized_job, summarize_jobs
from positions import CANONICAL_POSITIONS, filter_by_positions

# Greenhouse's board endpoint returns every posting in one response - unlike
# some ATS APIs, there's no pagination to worry about here. `content=true`
# includes the full HTML job description, which is what we turn into `description`.
GREENHOUSE_BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def fetch_jobs(board_token: str) -> list[dict]:
    """Fetch every posting on a company's Greenhouse board, normalized."""
    url = GREENHOUSE_BOARD_URL.format(token=board_token)
    try:
        response = requests.get(url=url, params={"content": "true"}, timeout=10)
    # Order matters: catch specific network/server issues before generic HTTP errors
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("request timed out - Greenhouse might be slow/down") from exc
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError("network error - check your connection/DNS") from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"unexpected request error: {exc}") from exc

    if response.status_code == 404:
        raise RuntimeError(f"job board not found for '{board_token}' - check the token is correct")
    if response.status_code != 200:
        raise RuntimeError(f"Greenhouse returned HTTP {response.status_code}")

    jobs = []
    for job in response.json().get("jobs", []):
        content = job.get("content")
        if not content:
            print(f"Unable to extract content for {job['title']}. Skipping it")
            # No description means nothing for the agent to ground on later - skip it.
            continue
        jobs.append(
            normalized_job(
                ats_job_id=job["id"],
                source="greenhouse",
                board_token=board_token,
                title=job["title"],
                description=html_to_text(content),
                url=job.get("absolute_url"),
                raw=job,
            )
        )
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board_tokens", nargs="+", help="Greenhouse board token(s), e.g. 'anthropic'")
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


# --- Your turn -------------------------------------------------------------
# Still open from the Slice 1 checklist:
#   - "every posting in department Y / office Z" (department/office filter -
#     `raw_json` still has `departments`/`offices` if you want it)
#   - "has posting ID N shown up before?" (this becomes the upsert dedupe key)
#
# Try it from a REPL (run from the repo root):
#   >>> import sys; sys.path.insert(0, "scripts")
#   >>> from explore_greenhouse import fetch_jobs
#   >>> from positions import filter_by_positions
#   >>> jobs = fetch_jobs("anthropic")
#   >>> [j["title"] for j in filter_by_positions(jobs, ["Software Engineer"])]
