"""Opt-in tracing for the agent, via Strands' built-in OpenTelemetry
instrumentation (strands.telemetry.StrandsTelemetry) - not something built
from scratch. Every strands.Agent already creates a span per model/tool
call internally (Agent.__init__'s self.tracer = get_tracer()); this module
just points those spans at Jaeger (docker-compose.yml's `jaeger` service)
instead of nowhere.

Why Jaeger instead of hand-formatting console output: a real trace UI
(http://localhost:16686 once `docker compose up -d jaeger` is running)
gives you a searchable timeline of every model/tool call - latency, token
usage, what the model said, what it called - for free, because that's
what a trace viewer is for. No formatting code to write or maintain here.

Complements, not replaces, groundwork.db.agent_runs: that table is
app-owned state other code queries (Slice 4's eval assertions, Slice 5's
"has this job been scored" gating) - Jaeger is for a human to look at
while debugging, not something application logic reads.

Kept separate from AWS/AgentCore entirely: Jaeger here has no dependency
on Bedrock AgentCore Runtime - it's a local dev tool, like the Postgres
container. Production tracing (AgentCore Observability, or shipping OTLP
to Jaeger/Langfuse/anything else hosted) is a separate, later decision -
see BUILD_PLAN.md's Slice 9 (deployment).
"""

from functools import lru_cache

from strands.telemetry import StrandsTelemetry


@lru_cache
def enable_jaeger_tracing() -> None:
    """Send every model/tool call span to Jaeger (start it first:
    `docker compose up -d jaeger`), viewable at http://localhost:16686.

    Cached (lru_cache with no args, so it only actually runs once) because
    StrandsTelemetry() sets a global tracer provider - calling this more
    than once per process would attach duplicate exporters and send every
    span twice. Safe to call from anywhere that might run more than once
    in a process - each agent's entrypoint module calls this once at import
    time, gated on the GROUNDWORK_TRACE env var (see score_fit/agent.py and
    job_agent/agent.py), rather than a CLI flag now that there's no CLI.
    """
    StrandsTelemetry().setup_otlp_exporter(endpoint="http://localhost:4318/v1/traces")
