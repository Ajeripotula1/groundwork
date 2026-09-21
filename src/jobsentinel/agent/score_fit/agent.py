"""Score Fit Agent (BUILD_PLAN.md Slice 3): analyzes and scores how well a
job posting matches the candidate's profile (generated from their resume).

This module *is* the AgentCore Runtime deployment unit for this agent - one
`BedrockAgentCoreApp` per agent, in its own directory, because each agent
gets its own container/runtime (CLAUDE.md: "Agent | AgentCore Runtime |
Strands agent + tools, its own container"). jobsentinel.agent.job_agent.agent
is the other one; they don't share a runtime or an entrypoint.

Run locally without deploying (one-shot, no server):
    uv run python -m jobsentinel.agent.score_fit.agent '{"job_id": 182, "user_id": "user_2abc123"}'
    uv run python -m jobsentinel.agent.score_fit.agent '{"job_id": 182, "user_id": "user_2abc123", "profile_id": 3}'

Run the local AgentCore dev server (same ASGI app AgentCore Runtime runs in
prod, just on your machine):
    uv run python -m jobsentinel.agent.score_fit.agent
    # then: curl -X POST http://localhost:8080/invocations -d '{"job_id": 182, "user_id": "user_2abc123"}'

Deploy for real: `agentcore configure --entrypoint src/jobsentinel/agent/score_fit/agent.py`,
then `agentcore launch`. Invoke the deployed agent: `agentcore invoke '{"job_id": 182, "user_id": "user_2abc123"}'`.

`user_id` (a Clerk ID) is a plain payload field, not anything this module
verifies itself - the API layer's jobsentinel.api.auth.get_current_user_id
is the only place a token is ever checked (per CLAUDE.md's hard
architectural rule, the agent never calls the API, so it can't reuse that
dependency either); this module just trusts whatever caller already
authenticated the request and resolved this id. It's what scopes "the
current profile" to the right person - see get_latest_profile/get_profile
below.

Set JOBSENTINEL_TRACE=1 to send model/tool call spans to Jaeger (start it
first: `docker compose up -d jaeger`, view at http://localhost:16686) - see
jobsentinel.agent.shared.tracing.
"""

import json
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel, CacheConfig

from jobsentinel.agent.shared.pricing import estimate_cost_usd
from jobsentinel.agent.shared.schema import MATCH_DEFINITIONS, FitAssessment
from jobsentinel.agent.shared.tracing import enable_jaeger_tracing
from jobsentinel.config import get_settings
from jobsentinel.db.agent_runs import KIND_SCORE_FIT, end_run, log_tool_call, start_run
from jobsentinel.db.engine import get_engine
from jobsentinel.db.jobs import get_job
from jobsentinel.db.profile import get_latest_profile, get_profile

settings = get_settings()

if os.environ.get("JOBSENTINEL_TRACE"):
    enable_jaeger_tracing()

# There must be exactly one instance per deployment - this registers the
# ASGI server (/invocations, /ping) that AgentCore Runtime calls into.
app = BedrockAgentCoreApp()


def build_tools(
    job_id: int, run_id: int, user_id: str, profile_id: int | None = None
) -> list:
    """Bind get_job_info/get_profile_facts to one AgentRun so every call
    logs itself to `tool_calls` (BUILD_PLAN.md Slice 3: "Log every tool
    call to tool_calls") - see jobsentinel.db.agent_runs.log_tool_call. A
    factory, not module-level tools, because run_id/job_id/profile_id
    differ per invocation - see build_agent below.

    `job_id`/`profile_id`: which job get_job_info() and which profile
    get_profile_facts() resolve to. Deliberately NOT parameters on the
    tools themselves - the model has no way to know which id is "correct,"
    so letting it choose would just be a second place to hallucinate from
    (this bit Slice 5's Job Agent for real before its get_job_info was
    fixed to the same closure-bound pattern used here). Instead the caller
    (this module's invoke(), or Slice 4's eval harness scoring several
    fixture jobs) picks both up front and they're baked into the tool
    closures; the tool calls the model sees stay clean and argument-free.
    profile_id=None falls back to the latest submission - the common case
    where you're not deliberately testing against an older snapshot.
    """

    @tool
    def get_job_info() -> str:
        """
        Retrieve this run's job posting - title and description.

        Returns:
            job: Job title/description as a JSON str, or an error message
            if the job no longer exists.
        """
        engine = get_engine()
        job = get_job(engine=engine, job_id=job_id)
        # Explicit None check, not try/except - a missing job is an
        # expected outcome the model should see and react to, not an
        # exception. (An earlier version fell through to
        # `json.dumps(job_info)` with `job_info` never assigned when `job`
        # was None - an UnboundLocalError the try/except didn't actually
        # catch, since it happened after the except block.)
        if job is None:
            result = {"error": f"no job with id {job_id}"}
        else:
            result = {"title": job.get("title"), "description": job.get("description")}
        log_tool_call(engine, run_id, "get_job_info", {}, result)
        return json.dumps(result)

    @tool
    def get_profile_facts() -> str:
        """
        Retrieve the current profile (structured resume facts) to compare
        against jobs. Which profile this resolves to is fixed for this
        agent run - see build_tools()'s profile_id.

        Returns:
            profile: The profile data as a JSON str, or an error message if
            no matching profile exists.
        """
        engine = get_engine()
        # profile_id is closure-bound (see this function's docstring) and
        # was already resolved + ownership-checked once in invoke() below
        # before build_tools was ever called - no user_id filter needed on
        # this internal lookup. See get_profile's docstring for when a
        # user_id filter IS required (client-supplied ids).
        if profile_id is not None:
            profile = get_profile(engine, profile_id)
            not_found = f"no profile with id {profile_id}"
        else:
            profile = get_latest_profile(engine, user_id)
            not_found = "no profile has been submitted yet"
        if profile is None:
            result = {"error": not_found}
        else:
            result = {"profile": profile["data"]}
        log_tool_call(engine, run_id, "get_profile_facts", {"profile_id": profile_id}, result)
        return json.dumps(result)

    return [get_job_info, get_profile_facts]


_MATCH_DEFINITIONS_TEXT = "\n".join(
    f"- {match.value}: {definition}" for match, definition in MATCH_DEFINITIONS.items()
)

_SYSTEM_PROMPT_TEMPLATE = """You are JobSentinel's fit-scoring agent. Your job is to assess how well a
specific candidate matches a specific job posting, using only tools - never your own
assumptions or prior knowledge.

## Why grounding is non-negotiable

JobSentinel's entire premise is that it never invents experience the candidate hasn't
described, and never assumes things about a company or role it hasn't actually looked up.
You are the first step in that pipeline. A fit assessment that pads over gaps with
plausible-sounding guesses, or credits the candidate with skills "probably" implied by
their background, is a hallucination - indistinguishable in effect from inventing a resume
bullet. Treat it as seriously as that.

## Tools

- get_job_info(): this run's job posting - title and description.
- get_profile_facts(): the candidate's resume, as structured facts (contact info,
  education, work experience, projects, certifications, skills).

Call both before writing anything. If either returns an error (job/profile not found),
stop immediately and report exactly that error back - do not proceed to an analysis with
partial or assumed information, and do not retry with a different id than the one you were
given.

## Grounding rules (hard constraints)

1. Every claim about the candidate must trace to a specific item get_profile_facts()
   returned - a listed skill, a bullet point, a project, a certification. Never infer a
   skill from a job title or company name (e.g. do not assume "worked at a fintech" implies
   "knows PCI compliance" unless it's stated).
2. Every claim about the role must trace to get_job_info()'s description. Do not use
   outside knowledge about the company, its products, its interview process, its culture,
   or typical compensation/leveling for a role like this, even if you're confident it's
   accurate - that knowledge didn't come from a tool call this run made, so by this
   project's own grounding rule it doesn't count.
3. If the job description doesn't say enough to judge a specific requirement, say so
   explicitly ("the posting doesn't specify X") rather than assuming the candidate does or
   doesn't meet it.
4. Never round a partial/adjacent match up to a full match. "Used Postgres" is not the same
   as "expert in distributed systems" even if both appear in a bullet together - judge what
   is actually stated, not the most generous plausible reading of it.

## Output format

Your response is captured as structured fields, not free text - fill each one as follows:

**summary**: 2-3 sentences, the headline read on this match.

**strengths**: One entry per satisfied requirement. Each entry names the specific job
requirement and the specific profile fact that satisfies it - no entry without both halves.

**gaps**: One entry per unsatisfied requirement, classified by gap_type:
- not_mentioned: the profile is silent on this requirement
- contradicts: the profile suggests the opposite
- posting_underspecified: the job text doesn't say enough to judge this requirement
Don't force a requirement into not_mentioned/contradicts if the posting itself is the one
that's vague - that's posting_underspecified, a different kind of gap.

**match**: Exactly one of the categories below. Use the written definition to decide, not a
gut feeling - and don't round a borderline case up to the more flattering category.
{match_definitions}

**recommendation_note**: One sentence on what, if anything, the candidate should emphasize
or address before applying. This is not a resume or cover letter (that's a separate step) -
keep it to a single sentence of direction, separate from the match category itself.

## Voice

Every user-facing field (summary, strengths/gaps notes, recommendation_note) speaks directly
to the candidate as "you" - never in the third person ("the candidate should...") and never
by name, even though get_profile_facts() may return one. JobSentinel is single-user today, but
writing in second person now avoids rewriting every prompt once multi-user identity exists -
at that point third-person narration wouldn't even reliably say whose profile this is.

## Tone

Be direct and critical, not encouraging-by-default - a match category that's inflated to be
nice is actively harmful to someone deciding whether to spend time applying. Be concise: no
filler sentences, no restating the job description back at length before getting to the
analysis. Technical specificity beats generic praise ("led a 3-service migration to
event-driven architecture using Kafka" beats "has strong backend experience")."""

SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.format(match_definitions=_MATCH_DEFINITIONS_TEXT)


def build_agent(tools: list) -> Agent:
    """Construct a fresh Agent bound to `tools` (from build_tools above,
    already bound to one AgentRun for logging). A factory, not a
    module-level singleton - see invoke() below, which is the only place
    this gets called from in practice.
    """
    bedrock_model = BedrockModel(
        model_id=settings.bedrock_agent_model_id,  # Claude Sonnet 4.6 (Bedrock)
        region_name=settings.aws_region,
        # Anthropic prompt caching (see CacheConfig docstring): places a
        # cachePoint after the (large, static-per-run) grounding-rules
        # system prompt and after the tool specs. A repeat call within the
        # TTL (default 5m, no extra cost to opt into) reads that prefix
        # back near-free instead of billing it as fresh input tokens -
        # cheap for the common case here, re-scoring the same job/profile
        # while iterating. The first call in a burst still pays a slightly
        # higher "cache write" rate for that prefix, so this only pays off
        # across >=2 calls sharing it, not a single one-off run.
        cache_config=CacheConfig(strategy="auto", tools_ttl=True),
    )
    # callback_handler=None (-> Strands' null_callback_handler): Strands'
    # default callback_handler live-streams assistant text to stdout as
    # it's generated. Silenced here because invoke() below returns the
    # final AgentResult itself - leaving the default on would print the
    # full response twice under local/one-shot testing.
    #
    # structured_output_model=FitAssessment: forces every call on this agent
    # to end with a validated FitAssessment (see jobsentinel.agent.shared.schema)
    # instead of free-text markdown - the whole point being that
    # AgentResult.structured_output is what invoke() persists to
    # agent_runs.result for the Job Agent/the UI to read later.
    return Agent(
        model=bedrock_model,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        callback_handler=None,
        structured_output_model=FitAssessment,
    )


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    """AgentCore Runtime entrypoint for the Score Fit agent.

    Expected payload keys:
      job_id      (int, required) - the job to score
      user_id     (str, required) - Clerk ID of the candidate being scored;
        see this module's docstring for why this is a trusted payload field,
        not something re-verified here
      profile_id  (int, optional) - score against this specific profile
        snapshot instead of the latest submission (see build_tools' docstring)

    Returns the FitAssessment as a plain dict (the same shape persisted to
    agent_runs.result), or {"error": ...} for a bad/missing job or profile.
    Every run is logged via start_run/end_run before/after Bedrock is ever
    touched, same as the interactive CLI this replaced.
    """
    job_id = payload.get("job_id")
    user_id = payload.get("user_id")
    profile_id = payload.get("profile_id")

    if job_id is None:
        return {"error": "job_id is required"}
    if not user_id:
        return {"error": "user_id is required"}

    engine = get_engine()

    # Fail fast before opening a run at all - no point logging a run for
    # something that was never going to work.
    if get_job(engine, job_id) is None:
        return {"error": f"no job with id {job_id}"}
    # Resolve to one concrete id here rather than leaving "latest" to be
    # re-resolved later inside get_profile_facts() - this run's row (and
    # get_latest_successful_result's profile_id filter, which is what makes
    # "score this job against profile 1, then again against profile 3"
    # distinguishable afterward) needs one fixed id to record, not
    # "whatever was latest at tool-call time."
    #
    # get_profile(..., user_id) here (not the bare get_profile(id) the tool
    # closure below uses) is deliberate: `profile_id` at this point may be
    # client-supplied (the API's ScoreFitRequest.profile_id), so this is the
    # ownership check that stops one user from scoring against another
    # user's profile by guessing/enumerating its id - see get_profile's
    # docstring.
    if profile_id is not None:
        if get_profile(engine, profile_id, user_id) is None:
            return {"error": f"no profile with id {profile_id}"}
    else:
        profile = get_latest_profile(engine, user_id)
        if profile is None:
            return {"error": "no profile has been submitted yet"}
        profile_id = profile["id"]

    run = start_run(engine, job_id, kind=KIND_SCORE_FIT, profile_id=profile_id)
    agent = build_agent(build_tools(job_id, run["id"], user_id, profile_id))

    try:
        result = agent(f"Score the fit for job id {job_id}.")
    except Exception as exc:
        end_run(engine, run["id"], outcome=f"error: {exc}")
        raise

    # structured_output_model=FitAssessment (see build_agent) means the
    # agent loop isn't done until the model calls the schema's forced tool -
    # a None here would mean Strands' contract was violated, not a case to
    # handle gracefully.
    assessment = result.structured_output
    if assessment is None:
        end_run(engine, run["id"], outcome="error: no structured_output returned")
        raise RuntimeError("agent finished without producing a FitAssessment")

    usage = result.metrics.accumulated_usage
    # cacheReadInputTokens/cacheWriteInputTokens are only present when the
    # model/provider actually cached something this run - absent (not 0)
    # otherwise, hence .get(..., 0) rather than a direct key lookup. See
    # build_agent's cache_config and pricing.estimate_cost_usd.
    cache_read = usage.get("cacheReadInputTokens", 0)
    cache_write = usage.get("cacheWriteInputTokens", 0)
    cost = estimate_cost_usd(
        settings.bedrock_agent_model_id,
        usage["inputTokens"],
        usage["outputTokens"],
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    assessment_dict = assessment.model_dump(mode="json")
    end_run(
        engine,
        run["id"],
        outcome="success",
        result=assessment_dict,
        input_tokens=usage["inputTokens"],
        output_tokens=usage["outputTokens"],
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=cost,
    )

    return assessment_dict


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # One-shot local invocation, no server - see module docstring.
        print(json.dumps(invoke(json.loads(sys.argv[1])), indent=2))
    else:
        # Local AgentCore dev server - POST to http://localhost:8080/invocations,
        # or `agentcore invoke` once `agentcore configure` has run against this file.
        app.run()
