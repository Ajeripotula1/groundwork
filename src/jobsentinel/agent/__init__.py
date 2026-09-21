"""
Strands-based agent core: fit scoring and interview-driven resume/cover-letter
tailoring.

Two independent agents live under here, each its own subpackage because each
deploys to its own AgentCore Runtime container (CLAUDE.md's "Agent |
AgentCore Runtime | Strands agent + tools, its own container" - true per
agent, not once for the whole package):

    jobsentinel.agent.score_fit.agent  - fit-scoring (BUILD_PLAN.md Slice 3)
    jobsentinel.agent.job_agent.agent  - interview/resume/cover-letter (Slice 5)

Code both agents need (output schemas, cost estimation, local tracing) lives
in jobsentinel.agent.shared, not duplicated into each agent directory - same
"shared module, not per-unit duplication" rule CLAUDE.md applies to
jobsentinel.db.

No top-level re-exports here on purpose: importing `jobsentinel.agent` no
longer pulls in a specific agent's dependencies (each agent directory is
built/deployed independently) - import from the specific agent subpackage
you need, e.g. `from jobsentinel.agent.score_fit.agent import build_agent`.

Each agent module runs locally via its own AgentCore entrypoint - no
separate CLI (see each agent.py's module docstring for the run command).
"""
