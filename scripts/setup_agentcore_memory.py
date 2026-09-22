"""One-time setup: create (or fetch, if it already exists) JobSentinel's
AgentCore Memory resource for the Job Agent.

Run by hand, not as part of any deploy step - this provisions a real,
per-AWS-account resource, the same "do it once, by hand" split as running
`alembic upgrade head` yourself rather than having the app run migrations
as a side effect of a request:

    uv run python scripts/setup_agentcore_memory.py

Paste the printed memory ID into .env as BEDROCK_AGENT_MEMORY_ID (see
.env.example) - jobsentinel.agent.shared.memory reads it from there.

Short-term only for now: no `strategies=` passed to create_or_get_memory,
so this resource just stores raw conversation events (BUILD_PLAN.md Slice
5's short-term tier - scoped per (actor_id, session_id) at the call site,
not here). Long-term memory (a semantic/user-preference strategy scoped to
actor_id only, across jobs) is a deliberate follow-up: add a strategy here
once that scoping/extraction design is decided - MemoryClient assigns each
strategy's default namespace automatically, and
jobsentinel.agent.shared.memory.build_session_manager already accepts a
`retrieval_config` to point at it, no other code changes needed.
"""

from bedrock_agentcore.memory import MemoryClient

from jobsentinel.config import get_settings

MEMORY_NAME = "jobsentinel_job_agent"


def main() -> None:
    settings = get_settings()
    client = MemoryClient(region_name=settings.aws_region)

    # create_or_get_memory is idempotent by name - safe to re-run this
    # script (e.g. on a second machine) without creating a duplicate resource.
    memory = client.create_or_get_memory(
        name=MEMORY_NAME,
        description="JobSentinel Job Agent - per-job conversation memory",
    )
    memory_id = memory.get("memoryId") or memory.get("id")

    print(f"Memory ready: {memory_id}")
    print(f"Add to .env: BEDROCK_AGENT_MEMORY_ID={memory_id}")


if __name__ == "__main__":
    main()
