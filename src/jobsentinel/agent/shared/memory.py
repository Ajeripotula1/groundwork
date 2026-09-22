"""AgentCore Memory wiring shared by agent modules that need it (today,
that's just the Job Agent - Score Fit is single-shot per job and has no
ongoing conversation to remember).

Two tiers, per BUILD_PLAN.md Slice 5:
  - short-term: conversation history, scoped to (actor_id, session_id).
    build_session_manager below wires this up - Strands'
    AgentCoreMemorySessionManager restores prior turns on Agent
    construction and appends each new turn afterward, so no manual
    reload/persist code is needed at the call site.
  - long-term: durable, cross-job facts about the user, scoped to
    actor_id only. Not wired up here - it needs a memory strategy
    (namespace + extraction config) decided first. Once that exists, pass
    its namespace/RetrievalConfig as `retrieval_config` below;
    AgentCoreMemorySessionManager already knows how to retrieve and inject
    it (see its retrieve_customer_context hook) - no other change needed.

The Memory resource itself is created once, out of band, by
scripts/setup_agentcore_memory.py. This module only ever looks up an
existing memory_id (from settings) - it never creates one, same "provision
once by hand, read many times from config" split as a Postgres migration
vs. jobsentinel.db.

`actor_id` is the caller's real Clerk user ID (jobsentinel.api.auth's `sub`
claim) as of the minimal Clerk pass - every call site resolves it from an
authenticated request/CLI payload now, not a shared constant (see
job_agent.agent.invoke). This is what keeps one user's conversations out of
another's: (actor_id, session_id) together scope a Memory session, and
session_id alone (job-{job_id}-profile-{profile_id}) is NOT unique across
users, since jobsentinel.db.profile.Profile.id is a global sequence, not
per-user - the actor_id half of the key is load-bearing, not redundant.
"""

from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.integrations.strands.bedrock_converter import (
    AgentCoreMemoryConverter,
)
from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

from jobsentinel.config import get_settings


def job_session_id(job_id: int, profile_id: int) -> str:
    """Session ID for one (job, profile) Job Agent conversation.

    Pulled out as its own function so every call site (build_session_manager
    below, and the API router that starts/continues a turn or reads history)
    derives it the same way instead of each re-inventing the format
    independently.

    `profile_id` is part of the key, not just `job_id` - a conversation is
    grounded in one specific profile snapshot (see build_tools' docstring
    on why profile_id is baked in rather than model-supplied), so switching
    profiles for the same job must start a fresh AgentCore Memory session
    rather than continuing one that has an older profile's facts baked into
    its history. Callers must resolve a concrete id first (never None) -
    see job_agent.agent.invoke's profile resolution - so that "the latest
    profile" is pinned to one id for the lifetime of a session instead of
    silently drifting to a different id if a newer profile gets submitted
    mid-conversation.
    """
    return f"job-{job_id}-profile-{profile_id}"


def _require_memory_id() -> str:
    """Return the configured memory ID, or raise loudly if it's missing.

    Shared by build_session_manager and list_conversation below rather
    than duplicated - see build_session_manager's docstring for why this
    is a runtime check here instead of a required Settings field.
    """
    settings = get_settings()
    if not settings.bedrock_agent_memory_id:
        raise RuntimeError(
            "BEDROCK_AGENT_MEMORY_ID is not set. Run "
            "`uv run python scripts/setup_agentcore_memory.py` once and add "
            "the printed ID to .env (see .env.example)."
        )
    return settings.bedrock_agent_memory_id


def build_session_manager(
    actor_id: str,
    session_id: str,
    retrieval_config: dict[str, RetrievalConfig] | None = None,
) -> AgentCoreMemorySessionManager:
    """Construct a session manager scoped to one (actor_id, session_id) pair.

    Called fresh per turn/request rather than cached as a module-level
    singleton - same reasoning as build_agent in each agent module being a
    factory: the state this wraps lives in AgentCore Memory, not in this
    process, so there's nothing worth holding onto between calls.

    Raises:
        RuntimeError: see _require_memory_id above.
    """
    settings = get_settings()
    config = AgentCoreMemoryConfig(
        memory_id=_require_memory_id(),
        actor_id=actor_id,
        session_id=session_id,
        retrieval_config=retrieval_config,
    )
    return AgentCoreMemorySessionManager(config, region_name=settings.aws_region)


def list_conversation(actor_id: str, session_id: str) -> list[dict[str, str]]:
    """Fetch one session's conversation history straight from AgentCore
    Memory, flattened to a plain `[{"role": ..., "text": ...}, ...]`
    transcript (oldest first) for a human-readable view (e.g.
    `GET /jobs/{id}/agent`) - not full replay fidelity.

    Reads via the lower-level MemoryClient rather than
    AgentCoreMemorySessionManager.list_messages: that method needs an
    `agent_id`, which only exists once a Strands Agent has been
    constructed - this is a read-only history fetch with no Agent involved.
    Tool-call/result blocks are dropped, keeping only plain text content,
    since this is meant for display, not for seeding a new Agent's
    `messages`.

    Raises:
        RuntimeError: see _require_memory_id above.
    """
    settings = get_settings()
    client = MemoryClient(region_name=settings.aws_region)
    events = client.list_events(
        memory_id=_require_memory_id(),
        actor_id=actor_id,
        session_id=session_id,
    )

    transcript = []
    for session_message in AgentCoreMemoryConverter.events_to_messages(events):
        message = session_message.message
        text = "".join(
            block.get("text", "") for block in message.get("content", []) if "text" in block
        )
        if text:
            transcript.append({"role": message["role"], "text": text})
    return transcript
