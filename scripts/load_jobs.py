"""One-off script: pull a real Greenhouse board and load it into Postgres.

This is BUILD_PLAN.md Slice 1's loader - deliberately crude compared to
Slice 8's eventual production poller. There's no scheduling and no
diffing/change-tracking here: it just re-fetches everything and upserts,
so re-running this against a board you've already loaded is safe (existing
rows get overwritten in place, see groundwork.db.jobs.upsert_job) but not
efficient. That tradeoff is fine for now - the point of this slice is
"the agent can read one real job", not a production-grade ingestion path.

Only Greenhouse for now, matching BUILD_PLAN's "Greenhouse only for real
ingestion in early slices" scope decision - Ashby/Lever ingestion is a
later addition (Slice 8+), not required to unblock the agent in Slice 3.

Usage:
    python scripts/load_jobs.py <board_token> [<board_token> ...]
    python scripts/load_jobs.py anthropic
"""

import argparse

from explore_greenhouse import fetch_jobs

from groundwork.db.engine import get_engine
from groundwork.db.jobs import upsert_job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board_tokens", nargs="+", help="Greenhouse board token(s), e.g. 'anthropic'")
    args = parser.parse_args()

    # One Engine (one connection pool) reused across every board/job in this
    # run, rather than opening a fresh connection per upsert - same reason
    # get_engine() is cached in the first place.
    engine = get_engine()

    for board_token in args.board_tokens:
        try:
            jobs = fetch_jobs(board_token)
        except RuntimeError as exc:
            print(f"skipping '{board_token}': {exc}")
            continue

        print(f"loading {len(jobs)} jobs from '{board_token}'...")
        for job in jobs:
            row_id = upsert_job(engine, job)
            print(f"  [{row_id}] {job['title']!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
