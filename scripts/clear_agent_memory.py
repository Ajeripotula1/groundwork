"""Wipe the Job Agent's short-term AgentCore Memory - run by hand for a
clean dev/test slate, same "run by hand, not part of any deploy step"
category as setup_agentcore_memory.py.

Deletes every event in every session for one actor (--actor-id, a Clerk
user ID - see jobsentinel.agent.shared.memory's docstring on why actor_id
scoping is load-bearing now), not the whole Memory resource -
MemoryClient.delete_memory would also work, but it destroys the resource
itself, forcing a recreate and a new BEDROCK_AGENT_MEMORY_ID pasted into
.env, for no real benefit here: this project has no long-term memory
strategies configured yet, so there's nothing durable to lose either way,
just conversation history.

MemoryClient doesn't wrap ListSessions/DeleteEvent (only list_events, for
reading), so this talks to the boto3 bedrock-agentcore data-plane client
directly.

Usage:
    uv run python scripts/clear_agent_memory.py --actor-id user_2abc123              # every session
    uv run python scripts/clear_agent_memory.py --actor-id user_2abc123 --job-id 31  # just this job's sessions (every profile)
    uv run python scripts/clear_agent_memory.py --actor-id user_2abc123 --yes        # skip the confirmation prompt
"""

import argparse

import boto3

from jobsentinel.config import get_settings


def _list_sessions(client, memory_id: str, actor_id: str) -> list[str]:
    session_ids = []
    next_token = None
    while True:
        kwargs = {"memoryId": memory_id, "actorId": actor_id}
        if next_token:
            kwargs["nextToken"] = next_token
        resp = client.list_sessions(**kwargs)
        session_ids.extend(s["sessionId"] for s in resp.get("sessionSummaries", []))
        next_token = resp.get("nextToken")
        if not next_token:
            return session_ids


def _list_event_ids(client, memory_id: str, actor_id: str, session_id: str) -> list[str]:
    event_ids = []
    next_token = None
    while True:
        kwargs = {"memoryId": memory_id, "actorId": actor_id, "sessionId": session_id}
        if next_token:
            kwargs["nextToken"] = next_token
        resp = client.list_events(**kwargs)
        event_ids.extend(e["eventId"] for e in resp.get("events", []))
        next_token = resp.get("nextToken")
        if not next_token:
            return event_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--actor-id", required=True, help="Clerk user ID whose sessions to clear"
    )
    parser.add_argument(
        "--job-id", type=int, default=None, help="only clear this job's sessions (every profile)"
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.bedrock_agent_memory_id:
        raise SystemExit(
            "BEDROCK_AGENT_MEMORY_ID is not set - nothing to clear (see .env.example)."
        )
    memory_id = settings.bedrock_agent_memory_id
    client = boto3.client("bedrock-agentcore", region_name=settings.aws_region)

    session_ids = _list_sessions(client, memory_id, args.actor_id)
    if args.job_id is not None:
        # See jobsentinel.agent.shared.memory.job_session_id for this format
        # ("job-{job_id}-profile-{profile_id}") - matched by prefix since a
        # job can have a session per profile that's talked to it.
        prefix = f"job-{args.job_id}-profile-"
        session_ids = [s for s in session_ids if s.startswith(prefix)]

    if not session_ids:
        print("Nothing to clear.")
        return

    print(f"About to delete {len(session_ids)} session(s):")
    for session_id in session_ids:
        print(f"  {session_id}")

    if not args.yes:
        confirm = input("Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return

    total_events = 0
    for session_id in session_ids:
        event_ids = _list_event_ids(client, memory_id, args.actor_id, session_id)
        for event_id in event_ids:
            client.delete_event(
                memoryId=memory_id,
                actorId=args.actor_id,
                sessionId=session_id,
                eventId=event_id,
            )
        total_events += len(event_ids)
        print(f"  cleared {session_id} ({len(event_ids)} events)")

    print(f"Done - {total_events} event(s) deleted across {len(session_ids)} session(s).")


if __name__ == "__main__":
    main()
