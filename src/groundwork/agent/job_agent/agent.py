"""Job Agent (BUILD_PLAN.md Slice 5) - one continuous agent, per job, that:
    1. Interviews the user to close gaps identified by Score Fit (Slice 3).
    2. Drafts a tailored resume rewrite (text only) grounded in profile facts.
    3. Drafts a cover letter (text only) grounded in profile facts + job text.
    4. Answers open-ended fit questions, grounded in the stored Score Fit result.

One agent, not three, and not a master-orchestrator-plus-sub-agents split -
see CLAUDE.md/BUILD_PLAN.md's locked-in scope decision: all four share the
same job, profile, and grounding rules, and happen sequentially in one
conversation, so a single session with a wider toolset is enough. The model
itself decides which capability a given user message calls for and when the
interview phase is "done" - there is deliberately no fixed turn count or
phase-tracking flag in code; see SYSTEM_PROMPT's control-flow rules and
mark_interview_complete below.

This module *is* the AgentCore Runtime deployment unit for this agent - its
own `BedrockAgentCoreApp`/entrypoint, in its own directory, independent of
groundwork.agent.score_fit.agent's runtime (see that module's docstring).

No session state (yet). This module previously grew a Postgres-backed
substitute for both AgentCore Memory tiers - a job_agent_turns table for
per-job conversation history, and a record_answer tool that wrote facts
straight into the profile's interview_notes - so the Job Agent was testable
before Memory existed. Both were torn out deliberately (not an oversight)
now that real AgentCore Memory is about to be wired up on top of this
module, per BUILD_PLAN.md's own note not to let two systems become the
source of truth for the same thing. Until that wiring lands, invoke() below
is single-turn: every call builds a brand-new Agent with no prior messages,
so it won't remember earlier turns in "the same" conversation and has no way
to persist a volunteered fact. TODO once AgentCore Memory exists:
  - short-term tier, scoped to (actor_id=user, session_id=job-{job_id}) -
    replaces job_agent_turns; plug into build_agent's `messages` below.
  - long-term tier, scoped to actor_id only - replaces record_answer; add
    back as a tool once there's a real memory client to write through.

Run locally without deploying (one-shot, no server):
    uv run python -m groundwork.agent.job_agent.agent '{"job_id": 182, "message": "help me tailor my resume"}'

Run the local AgentCore dev server:
    uv run python -m groundwork.agent.job_agent.agent
    # then: curl -X POST http://localhost:8080/invocations -d '{"job_id": 182, "message": "..."}'

Deploy for real: `agentcore configure --entrypoint src/groundwork/agent/job_agent/agent.py`,
then `agentcore launch`. Invoke the deployed agent: `agentcore invoke '{"job_id": 182, "message": "..."}'`.

Set GROUNDWORK_TRACE=1 to send model/tool call spans to Jaeger - see
groundwork.agent.shared.tracing.
"""

import json
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel

from groundwork.agent.shared.pricing import estimate_cost_usd
from groundwork.agent.shared.schema import MATCH_DEFINITIONS
from groundwork.agent.shared.tracing import enable_jaeger_tracing
from groundwork.config import get_settings
from groundwork.db.agent_runs import (
    KIND_JOB_AGENT,
    KIND_SCORE_FIT,
    end_run,
    get_latest_successful_result,
    log_tool_call,
    start_run,
)
from groundwork.db.engine import get_engine
from groundwork.db.jobs import get_job
from groundwork.db.profile import get_latest_profile, get_profile

settings = get_settings()

if os.environ.get("GROUNDWORK_TRACE"):
    enable_jaeger_tracing()

# There must be exactly one instance per deployment - see
# groundwork.agent.score_fit.agent's app for the same pattern.
app = BedrockAgentCoreApp()


def build_tools(job_id: int, run_id: int, profile_id: int | None = None) -> list:
    """Bind every tool to one job + one AgentRun (this turn) + one profile,
    same factory pattern as groundwork.agent.score_fit.agent.build_tools -
    see that module's docstring for why `profile_id` is baked in rather
    than a model-supplied argument.

    Not reused from groundwork.agent.score_fit.agent directly: those tools
    log against a Score Fit run (one AgentRun per whole `score` invocation),
    while these log against a Job Agent *turn* (one AgentRun per message
    exchange - see KIND_JOB_AGENT in groundwork.db.agent_runs). Same shape,
    different logging granularity - small enough duplication that sharing
    it would cost more (a shared factory parameterized over "what counts as
    one run") than it'd save.
    """

    @tool
    def get_job_info() -> str:
        """
        Retrieve this conversation's job posting - title and description.

        Returns:
            The job title/description as a JSON str, or an error message
            if the job no longer exists.
        """
        engine = get_engine()
        job = get_job(engine=engine, job_id=job_id)
        if job is None:
            result = {"error": f"no job with id {job_id}"}
        else:
            result = {"title": job.get("title"), "description": job.get("description")}
        log_tool_call(engine, run_id, "get_job_info", {}, result)
        return json.dumps(result)

    @tool
    def get_profile_facts() -> str:
        """
        Retrieve the current profile (structured resume facts) to ground
        resume/cover-letter drafting and gap-closing questions.

        Returns:
            The profile data as a JSON str, or an error message if no
            matching profile exists.
        """
        engine = get_engine()
        if profile_id is not None:
            profile = get_profile(engine, profile_id)
            not_found = f"no profile with id {profile_id}"
        else:
            profile = get_latest_profile(engine)
            not_found = "no profile has been submitted yet"
        if profile is None:
            result = {"error": not_found}
        else:
            result = {"profile": profile["data"]}
        log_tool_call(engine, run_id, "get_profile_facts", {"profile_id": profile_id}, result)
        return json.dumps(result)

    @tool
    def get_fit_assessment() -> str:
        """
        Retrieve the stored Score Fit result for this job - the match
        category, strengths, and gaps already identified. This is what
        grounds the interview (ask about the gaps listed here, not gaps
        you guess at) and any fit Q&A - never characterize the fit from
        your own read of the job/profile when this tool has already done
        that analysis.

        Returns:
            The stored FitAssessment as a JSON str, or an error message if
            no successful Score Fit run exists for this job (shouldn't
            happen - invoke() gates the Job Agent on this - but handled
            explicitly rather than assumed).
        """
        engine = get_engine()
        assessment = get_latest_successful_result(engine, job_id, kind=KIND_SCORE_FIT)
        if assessment is None:
            result = {"error": f"no successful Score Fit run exists for job {job_id}"}
        else:
            result = {"assessment": assessment}
        log_tool_call(engine, run_id, "get_fit_assessment", {}, result)
        return json.dumps(result)

    @tool
    def mark_interview_complete() -> str:
        """
        Call this once - and only once - you've asked enough questions to
        close the gaps that matter for this job (or the user says they'd
        rather skip ahead). There is no fixed number of questions; use
        get_fit_assessment()'s gaps to judge when you've covered what's
        worth covering. After calling this, move on to drafting or
        answering questions instead of continuing to ask for more facts,
        unless the user raises something new themselves.

        Returns:
            A JSON str confirming the interview phase is closed.
        """
        engine = get_engine()
        result = {"interview_complete": True}
        log_tool_call(engine, run_id, "mark_interview_complete", {}, result)
        return json.dumps(result)

    return [
        get_job_info,
        get_profile_facts,
        get_fit_assessment,
        mark_interview_complete,
    ]


_MATCH_DEFINITIONS_TEXT = "\n".join(
    f"- {match.value}: {definition}" for match, definition in MATCH_DEFINITIONS.items()
)

SYSTEM_PROMPT = f"""You are GroundWork's Job Agent. You help one candidate with one specific job,
across a single continuous conversation that may cover several things in any order: closing
gaps between their profile and the job, drafting a tailored resume rewrite, drafting a cover
letter, and answering open-ended questions about the fit. You decide which of these a given
message calls for - there is no fixed script or turn count.

## Why grounding is non-negotiable

GroundWork never invents experience the candidate hasn't described, and never assumes things
about a company or role it hasn't actually looked up. Every claim in a drafted resume line,
cover letter sentence, or Q&A answer must trace to something get_profile_facts() or
get_fit_assessment() actually returned. Padding a gap with a plausible-sounding guess is a
hallucination, indistinguishable in effect from inventing a resume bullet - treat it as
seriously as that. Note: you currently have no way to persist a fact the user volunteers
mid-conversation (record_answer is gone pending AgentCore Memory - see this module's
docstring) - if something they tell you isn't already in get_profile_facts(), you can use it
within *this* reply, but say plainly that you won't remember it next time, rather than implying
it's been saved anywhere.

## Tools

- get_job_info(): this conversation's job posting - title and description.
- get_profile_facts(): the candidate's current resume facts.
- get_fit_assessment(): the stored Score Fit result for this job - match category, strengths,
  gaps. Ground the interview and any fit Q&A in this; don't re-derive your own read of the fit.
- mark_interview_complete(): call once you've covered what matters (per get_fit_assessment's
  gaps) or the user asks to skip ahead. No fixed number of questions.

Call get_job_info and get_profile_facts at the start of a new conversation about this job, and
get_fit_assessment before your first substantive reply - don't proceed on assumptions about
any of the three.

## Match categories (context for get_fit_assessment's output)

{_MATCH_DEFINITIONS_TEXT}

## Control flow (hard rules)

1. Ask one focused question at a time, not a checklist dump - this is a conversation, not a form.
2. Prioritize questions that close a gap get_fit_assessment() actually flagged. Don't ask about
   something already covered in get_profile_facts().
3. Call mark_interview_complete() yourself when you've asked enough - never ask a fixed number
   of questions "because that's usually enough." After calling it, don't keep probing for more
   facts unless the user brings up something new.
4. A resume rewrite or cover letter is text only (no file generation) - every line must trace
   to a fact from get_profile_facts(), plus (for the cover letter) the job's own text. If a
   section would need a fact nobody's given you, ask for it or say the gap remains open - don't
   fill it with something plausible-sounding.
5. If the user just wants to talk through the fit (no drafting requested), answer directly from
   get_fit_assessment() and get_profile_facts() - you don't have to run an interview first.

## Voice

You are talking directly to the candidate, in a live conversation with them - address them as
"you" in every reply, question, and drafted line. Never slip into the third person ("the
candidate should...", "they mentioned...") and never refer to them by name, even though
get_profile_facts() may return one - that name identifies whose profile this is, it isn't how
you address them. This also anticipates multi-user identity: once other users exist,
third-person narration by name wouldn't even reliably say who you're talking to.

## Tone

Direct and specific, like a colleague reviewing a real application - not generically
encouraging. Prefer citing the specific fact/requirement over restating the job description or
profile back at length."""


def build_agent(tools: list, messages: list | None = None) -> Agent:
    """Construct a fresh Agent for one turn, bound to `tools` (from
    build_tools above) and seeded with `messages` - the conversation so
    far. A factory, not a module-level singleton, same reasoning as
    groundwork.agent.score_fit.agent's build_agent: state lives outside
    this object, not inside it.

    `messages` is always None today - invoke() below has no session store
    to reload it from (see this module's docstring: the Postgres-backed one
    was torn out, AgentCore Memory's short-term tier isn't wired up yet).
    The parameter stays because that future wiring is a call-site change
    (pass real prior messages into build_agent), not a signature change.

    No structured_output_model, unlike Score Fit's build_agent - the Job
    Agent's output is free-form conversational text (an interview
    question, a drafted resume paragraph, a Q&A answer), not one fixed
    schema every turn could be forced into.
    """
    bedrock_model = BedrockModel(
        model_id=settings.bedrock_agent_model_id,
        region_name=settings.aws_region,
    )
    return Agent(
        model=bedrock_model,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
        # See groundwork.agent.score_fit.agent.build_agent's docstring:
        # invoke() below returns the reply itself, so the default streaming
        # callback_handler would print it twice under local/one-shot testing.
        callback_handler=None,
    )


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    """AgentCore Runtime entrypoint for the Job Agent.

    Expected payload keys:
      job_id      (int, required) - which job's conversation this turn belongs to
      message     (str, required) - the candidate's message this turn
      profile_id  (int, optional) - use this specific profile snapshot instead
        of the latest submission (see build_tools' docstring)

    Gated on a successful Score Fit run for this job (Slice 5's gating
    requirement) - checked here via get_latest_successful_result, not
    re-derived by the agent itself. No conversation history is reloaded -
    see this module's docstring: every call is single-turn until AgentCore
    Memory's short-term tier is wired up to replace what used to be a
    Postgres-backed session store.
    """
    job_id = payload.get("job_id")
    message = payload.get("message")
    profile_id = payload.get("profile_id")

    if job_id is None:
        return {"error": "job_id is required"}
    if not message:
        return {"error": "message is required"}

    engine = get_engine()

    job = get_job(engine, job_id)
    if job is None:
        return {"error": f"no job with id {job_id}"}

    if get_latest_successful_result(engine, job_id, kind=KIND_SCORE_FIT) is None:
        return {
            "error": (
                f"I don't have a fit score for \"{job['title']}\" yet, so I can't dig into "
                "it with you - run Score Fit on this job first and come back once that's "
                "done. That way I'll actually know how you stack up against it instead of "
                "guessing."
            )
        }

    run = start_run(engine, job_id, kind=KIND_JOB_AGENT)
    agent = build_agent(build_tools(job_id, run["id"], profile_id))

    try:
        result = agent(message)
    except Exception as exc:
        end_run(engine, run["id"], outcome=f"error: {exc}")
        raise

    reply = str(result).strip()
    usage = result.metrics.accumulated_usage
    cost = estimate_cost_usd(
        settings.bedrock_agent_model_id, usage["inputTokens"], usage["outputTokens"]
    )
    end_run(
        engine,
        run["id"],
        outcome="success",
        result={"reply": reply},
        input_tokens=usage["inputTokens"],
        output_tokens=usage["outputTokens"],
        cost_usd=cost,
    )

    return {"reply": reply}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # One-shot local invocation, no server - see module docstring.
        print(json.dumps(invoke(json.loads(sys.argv[1])), indent=2))
    else:
        # Local AgentCore dev server - POST to http://localhost:8080/invocations,
        # or `agentcore invoke` once `agentcore configure` has run against this file.
        app.run()
