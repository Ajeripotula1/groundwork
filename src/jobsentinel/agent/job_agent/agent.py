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
jobsentinel.agent.score_fit.agent's runtime (see that module's docstring).

Short-term session memory: wired up via jobsentinel.agent.shared.memory's
AgentCoreMemorySessionManager (see build_agent/invoke below) - this module
previously grew a Postgres-backed substitute (a job_agent_turns table) so
the Job Agent was testable before Memory existed; that table was torn out
deliberately once real AgentCore Memory was ready, per BUILD_PLAN.md's own
note not to let two systems become the source of truth for the same thing.

Long-term memory is still a TODO: a record_answer tool that wrote facts
straight into the profile's interview_notes was torn out the same way, and
hasn't been re-implemented yet - it needs a memory strategy scoped to
actor_id only (across jobs) decided first, then a tool that writes through
it, per BUILD_PLAN.md Slice 5.

Run locally without deploying (one-shot, no server):
    uv run python -m jobsentinel.agent.job_agent.agent '{"job_id": 182, "user_id": "user_2abc123", "message": "help me tailor my resume"}'

Run the local AgentCore dev server:
    uv run python -m jobsentinel.agent.job_agent.agent
    # then: curl -X POST http://localhost:8080/invocations -d '{"job_id": 182, "user_id": "user_2abc123", "message": "..."}'

Deploy for real: `agentcore configure --entrypoint src/jobsentinel/agent/job_agent/agent.py`,
then `agentcore launch`. Invoke the deployed agent: `agentcore invoke '{"job_id": 182, "user_id": "user_2abc123", "message": "..."}'`.

`user_id` (a Clerk ID) is a plain payload field the API layer resolves via
jobsentinel.api.auth.get_current_user_id and hands down - see
jobsentinel.agent.score_fit.agent's module docstring for why this module
doesn't (and, per the hard architectural rule, can't) verify a token
itself. It's both the AgentCore Memory actor_id for this conversation (see
build_session_manager below) and what scopes "the current profile."

Set JOBSENTINEL_TRACE=1 to send model/tool call spans to Jaeger - see
jobsentinel.agent.shared.tracing.
"""

import json
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel, CacheConfig
from strands.session.session_manager import SessionManager

from jobsentinel.agent.shared.memory import build_session_manager, job_session_id
from jobsentinel.agent.shared.pricing import estimate_cost_usd
from jobsentinel.agent.shared.schema import MATCH_DEFINITIONS
from jobsentinel.agent.shared.tracing import enable_jaeger_tracing
from jobsentinel.config import get_settings
from jobsentinel.db.agent_runs import (
    KIND_JOB_AGENT,
    KIND_SCORE_FIT,
    end_run,
    get_latest_successful_result,
    log_tool_call,
    start_run,
)
from jobsentinel.db.engine import get_engine
from jobsentinel.db.jobs import get_job
from jobsentinel.db.profile import get_latest_profile, get_profile

settings = get_settings()

if os.environ.get("JOBSENTINEL_TRACE"):
    enable_jaeger_tracing()

# There must be exactly one instance per deployment - see
# jobsentinel.agent.score_fit.agent's app for the same pattern.
app = BedrockAgentCoreApp()


def build_tools(
    job_id: int, run_id: int, user_id: str, profile_id: int | None = None
) -> list:
    """Bind every tool to one job + one AgentRun (this turn) + one profile,
    same factory pattern as jobsentinel.agent.score_fit.agent.build_tools -
    see that module's docstring for why `profile_id` is baked in rather
    than a model-supplied argument.

    Not reused from jobsentinel.agent.score_fit.agent directly: those tools
    log against a Score Fit run (one AgentRun per whole `score` invocation),
    while these log against a Job Agent *turn* (one AgentRun per message
    exchange - see KIND_JOB_AGENT in jobsentinel.db.agent_runs). Same shape,
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
        # profile_id is closure-bound and already resolved + ownership-
        # checked once in invoke() below before build_tools was called - see
        # score_fit.agent's identical tool for the same reasoning.
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
            no successful Score Fit run exists for this job/profile pair
            (shouldn't happen - invoke() gates the Job Agent on this - but
            handled explicitly rather than assumed).
        """
        engine = get_engine()
        # Filtered by this run's profile_id, not "whichever Score Fit run
        # for this job is newest" - two profiles scored against the same
        # job produce two different FitAssessments, and this conversation
        # is grounded in one specific profile (build_tools' profile_id),
        # not whichever was scored most recently. See get_latest_successful_
        # result's docstring in jobsentinel.db.agent_runs.
        assessment = get_latest_successful_result(
            engine, job_id, kind=KIND_SCORE_FIT, profile_id=profile_id
        )
        if assessment is None:
            result = {
                "error": f"no successful Score Fit run exists for job {job_id} "
                f"against profile {profile_id}"
            }
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

SYSTEM_PROMPT = f"""You are JobSentinel's Job Agent. You help one candidate with one specific job,
across a single continuous conversation that may cover several things in any order: closing
gaps between their profile and the job, drafting a tailored resume rewrite, drafting a cover
letter, and answering open-ended questions about the fit. You decide which of these a given
message calls for - there is no fixed script or turn count.

## Why grounding is non-negotiable

JobSentinel never invents experience the candidate hasn't described, and never assumes things
about a company or role it hasn't actually looked up. Every claim in a drafted resume line,
cover letter sentence, or Q&A answer must trace to something get_profile_facts() or
get_fit_assessment() actually returned. Padding a gap with a plausible-sounding guess is a
hallucination, indistinguishable in effect from inventing a resume bullet - treat it as
seriously as that. Note: you'll recall what the user tells you earlier in *this* job's
conversation (short-term memory), but nothing volunteered here becomes a durable profile fact
or carries over to a different job yet (record_answer is gone pending AgentCore Memory's
long-term tier - see this module's docstring) - if something they tell you isn't already in
get_profile_facts(), you can use it for the rest of this conversation, but say plainly that it
won't be remembered for other jobs or carried into their profile, rather than implying it's
been saved anywhere durable.

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


def build_agent(tools: list, session_manager: SessionManager) -> Agent:
    """Construct a fresh Agent for one turn, bound to `tools` (from
    build_tools above) and `session_manager` (from
    jobsentinel.agent.shared.memory.build_session_manager). A factory, not a
    module-level singleton, same reasoning as jobsentinel.agent.score_fit.
    agent's build_agent: state lives outside this object, not inside it -
    here, in AgentCore Memory rather than this process.

    Passing session_manager to Agent() replaces what used to be a manual
    `messages=` seed: Strands restores this (actor_id, session_id)'s prior
    turns during construction and appends each new one afterward on its
    own, so there's no reload/persist code to write here.

    No structured_output_model, unlike Score Fit's build_agent - the Job
    Agent's output is free-form conversational text (an interview
    question, a drafted resume paragraph, a Q&A answer), not one fixed
    schema every turn could be forced into.
    """
    bedrock_model = BedrockModel(
        model_id=settings.bedrock_agent_model_id,
        region_name=settings.aws_region,
        # See jobsentinel.agent.score_fit.agent.build_agent's cache_config
        # comment for the mechanics. It matters more here: every turn
        # resends this job's *entire* prior conversation (restored from
        # AgentCore Memory via session_manager below), so a long interview
        # would otherwise re-bill that whole growing history as fresh input
        # on each message. CacheConfig with no explicit cache_key derives
        # one from this Agent's session_manager (session_id = this job's
        # conversation), so consecutive turns of the same job share a cache
        # prefix instead of each paying full price for turns already sent.
        cache_config=CacheConfig(strategy="auto", tools_ttl=True),
    )
    return Agent(
        model=bedrock_model,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        session_manager=session_manager,
        # See jobsentinel.agent.score_fit.agent.build_agent's docstring:
        # invoke() below returns the reply itself, so the default streaming
        # callback_handler would print it twice under local/one-shot testing.
        callback_handler=None,
    )


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    """AgentCore Runtime entrypoint for the Job Agent.

    Expected payload keys:
      job_id      (int, required) - which job's conversation this turn belongs to
      user_id     (str, required) - Clerk ID of the candidate (see this
        module's docstring); also the AgentCore Memory actor_id for this
        conversation
      message     (str, required) - the candidate's message this turn
      profile_id  (int, optional) - use this specific profile snapshot instead
        of the latest submission (see build_tools' docstring)

    Gated on a successful Score Fit run for this (job, profile) pair
    (Slice 5's gating requirement) - checked here via
    get_latest_successful_result, not re-derived by the agent itself.
    Conversation history for this (job, profile) pair is restored from
    AgentCore Memory (see build_session_manager below), so this *is* a
    continuation of earlier turns of the same profile's conversation, not a
    fresh conversation each call - the statelessness is only about this
    process, not the conversation itself.
    """
    job_id = payload.get("job_id")
    user_id = payload.get("user_id")
    message = payload.get("message")
    profile_id = payload.get("profile_id")

    if job_id is None:
        return {"error": "job_id is required"}
    if not user_id:
        return {"error": "user_id is required"}
    if not message:
        return {"error": "message is required"}

    engine = get_engine()

    job = get_job(engine, job_id)
    if job is None:
        return {"error": f"no job with id {job_id}"}

    # Resolve profile_id to one concrete id *before* the gate check or the
    # session is built - not deferred to get_profile_facts()'s own
    # None-handling like build_tools' docstring describes for the tool-call
    # path. Both the gate below and the session are keyed on (job_id,
    # profile_id) (see get_latest_successful_result/job_session_id), so
    # "latest" has to be pinned to one id for this whole turn: resolving it
    # lazily inside the tool would let two turns of what looks like "the
    # same session" silently key against different profiles if a newer one
    # gets submitted in between, defeating the point of keying on it at all.
    # get_profile(..., user_id) here is the ownership check - profile_id may
    # be client-supplied (JobAgentTurnRequest.profile_id), so this stops one
    # user from continuing a conversation grounded in another user's
    # profile by guessing/enumerating its id. See get_profile's docstring.
    if profile_id is not None:
        profile = get_profile(engine, profile_id, user_id)
        if profile is None:
            return {"error": f"no profile with id {profile_id}"}
    else:
        profile = get_latest_profile(engine, user_id)
        if profile is None:
            return {"error": "no profile has been submitted yet"}
    profile_id = profile["id"]

    # Gated on a successful Score Fit run for *this profile*, not just this
    # job - a job scored against profile 1 doesn't mean profile 3 has been
    # scored, and interviewing/drafting against profile 3 while grounded in
    # profile 1's gaps would reproduce the same cross-profile bleed the
    # session-scoping fix addressed, just via the fit assessment instead of
    # conversation memory.
    if get_latest_successful_result(engine, job_id, kind=KIND_SCORE_FIT, profile_id=profile_id) is None:
        return {
            "error": (
                f"I don't have a fit score for \"{job['title']}\" against this profile yet, "
                "so I can't dig into it with you - run Score Fit against this profile first "
                "and come back once that's done. That way I'll actually know how you stack "
                "up against it instead of guessing."
            )
        }

    run = start_run(engine, job_id, kind=KIND_JOB_AGENT, profile_id=profile_id)
    session_manager = build_session_manager(
        actor_id=user_id,
        session_id=job_session_id(job_id, profile_id),
    )
    agent = build_agent(build_tools(job_id, run["id"], user_id, profile_id), session_manager)

    try:
        result = agent(message)
    except Exception as exc:
        end_run(engine, run["id"], outcome=f"error: {exc}")
        raise

    reply = str(result).strip()
    usage = result.metrics.accumulated_usage
    # See jobsentinel.agent.score_fit.agent.invoke's identical lines - same
    # reasoning, .get(..., 0) because these keys are absent (not 0) on any
    # call that didn't hit/write a cache.
    cache_read = usage.get("cacheReadInputTokens", 0)
    cache_write = usage.get("cacheWriteInputTokens", 0)
    cost = estimate_cost_usd(
        settings.bedrock_agent_model_id,
        usage["inputTokens"],
        usage["outputTokens"],
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    end_run(
        engine,
        run["id"],
        outcome="success",
        result={"reply": reply},
        input_tokens=usage["inputTokens"],
        output_tokens=usage["outputTokens"],
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
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
