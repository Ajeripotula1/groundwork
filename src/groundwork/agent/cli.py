"""CLI entrypoint for the agent core (BUILD_PLAN.md Slice 3).

Runs locally, before this ever touches AgentCore Runtime (see
groundwork/agent/__init__.py) - this is how you manually exercise the
agent and check its rationale isn't citing anything the tools didn't
return, per Slice 3's own manual-verification step.

Usage:
    python -m groundwork.agent.cli score <job_id> [--profile-id ID]
    python -m groundwork.agent.cli score 182
    python -m groundwork.agent.cli score 182 --profile-id 3

--profile-id lets you score the same job against a specific profile
snapshot instead of the latest submission - useful for testing multiple
profiles/resume versions against the same posting (Slice 4's eval harness
will want exactly this: one job x several profile fixtures).
"""

import argparse
import sys

from groundwork.agent.main import build_agent, build_tools
from groundwork.agent.pricing import estimate_cost_usd
from groundwork.config import get_settings
from groundwork.db.agent_runs import end_run, start_run
from groundwork.db.engine import get_engine
from groundwork.db.jobs import get_job
from groundwork.db.profile import get_latest_profile, get_profile


def score(job_id: int, profile_id: int | None = None) -> None:
    """Run the fit-scoring agent against one job and one profile (the
    given `profile_id`, or the latest submission if None), printing the
    result. Every call is logged: start_run() opens an AgentRun before
    Bedrock is ever touched, end_run() closes it out either way (success
    or exception) with token usage/estimated cost.
    """
    engine = get_engine()

    # Fail fast before opening a run at all - no point logging a run for
    # something that was never going to work.
    if get_job(engine, job_id) is None:
        print(f"no job with id {job_id}", file=sys.stderr)
        raise SystemExit(1)
    if profile_id is not None:
        if get_profile(engine, profile_id) is None:
            print(f"no profile with id {profile_id}", file=sys.stderr)
            raise SystemExit(1)
    elif get_latest_profile(engine) is None:
        print("no profile has been submitted yet", file=sys.stderr)
        raise SystemExit(1)

    run = start_run(engine, job_id)
    agent = build_agent(build_tools(run["id"], profile_id))

    try:
        result = agent(f"Score the fit for job id {job_id}.")
    except Exception as exc:
        end_run(engine, run["id"], outcome=f"error: {exc}")
        raise

    usage = result.metrics.accumulated_usage
    cost = estimate_cost_usd(
        get_settings().bedrock_agent_model_id,
        usage["inputTokens"],
        usage["outputTokens"],
    )
    end_run(
        engine,
        run["id"],
        outcome="success",
        input_tokens=usage["inputTokens"],
        output_tokens=usage["outputTokens"],
        cost_usd=cost,
    )

    print(result)
    cost_str = f" | est. cost: ${cost:.4f}" if cost is not None else ""
    print(
        f"[run {run['id']}] tokens: in={usage['inputTokens']} out={usage['outputTokens']}{cost_str}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    score_parser = subparsers.add_parser(
        "score", help="Score one job's fit against a profile"
    )
    score_parser.add_argument("job_id", type=int)
    score_parser.add_argument(
        "--profile-id",
        type=int,
        default=None,
        help="Score against this specific profile snapshot instead of the latest submission",
    )

    args = parser.parse_args()
    if args.command == "score":
        score(args.job_id, args.profile_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
