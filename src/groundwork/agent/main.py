"""Agent Entry point file
This file contains the implementation for all the Agents capabilities:
    1. Research Company: analyze the posting entry from DB and also additional websearch tool to learn more about the company, project, or role
    2. [Done] Score Fit: be able to analyze and understand the job, compare it againsts user profile (generated from user's resume)
    3. [In Progress] Resume Optimization: Work with user to identify strenghts, weaknesses, and WORK with user (interactive interview still chat) to bridge those gaps, rewrite points, or suggest changes. This prevents hallucination, and encourages personalized touch to resume. The end result is a resume rewritten with user's changes and presented to user via text (don't need to worry about genreating and formatting files yet)
    4. Cover Letter: Same process, pull from company research, interview user on interests, and generate cover letter content
    5. [Stretch]: Mock Interivew and Prep Agent that creates sessions where user's are asked common interview questions, job/ role specific questions, and given feedback and bonus homeowork/ research to better prepare
"""
import json

from strands import Agent, tool
from strands.models import BedrockModel

from groundwork.config import get_settings
from groundwork.db.agent_runs import log_tool_call
from groundwork.db.engine import get_engine
from groundwork.db.jobs import get_job
from groundwork.db.profile import get_latest_profile, get_profile

settings = get_settings()


def build_tools(run_id: int, profile_id: int | None = None) -> list:
    """Bind get_job_info/get_profile_facts to one AgentRun so every call
    logs itself to `tool_calls` (BUILD_PLAN.md Slice 3: "Log every tool
    call to tool_calls") - see groundwork.db.agent_runs.log_tool_call. A
    factory, not module-level tools, because run_id (and now profile_id)
    differ per invocation - see build_agent below.

    `profile_id`: which profile get_profile_facts() resolves to.
    Deliberately NOT a parameter on the tool itself - the model has no way
    to know which id is "correct," so letting it choose would just be a
    second place to hallucinate from. Instead the caller (the CLI, or
    Slice 4's eval harness running the same job against several profile
    fixtures) picks the profile up front and it's baked into the tool
    closure; the tool call the model sees stays a clean, argument-free
    "give me the profile." None (the default) falls back to the latest
    submission - the common case where you're not deliberately testing
    against an older snapshot.
    """

    @tool
    def get_job_info(id: int) -> str:
        """
        Retrieve information about the selected Job posting

        Args:
            id: Job ID that will be used to query the database

        Returns:
            job: Job title/description as a JSON str, or an error message
            if no job exists with that id.
        """
        engine = get_engine()
        job = get_job(engine=engine, job_id=id)
        # Explicit None check, not try/except - a missing job is an
        # expected outcome the model should see and react to, not an
        # exception. (The previous version fell through to
        # `json.dumps(job_info)` with `job_info` never assigned when `job`
        # was None - an UnboundLocalError the try/except didn't actually
        # catch, since it happened after the except block.)
        if job is None:
            result = {"error": f"no job with id {id}"}
        else:
            result = {"title": job.get("title"), "description": job.get("description")}
        log_tool_call(engine, run_id, "get_job_info", {"id": id}, result)
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

    return [get_job_info, get_profile_facts]


# Production system prompt for Slice 3's fit-scoring agent. Written out in
# full per explicit request - this is normally the "design exercise" part
# of this slice (BUILD_PLAN.md), left for hands-on iteration. Design
# decisions baked in here, so they're visible instead of implicit:
#   - 0-100 integer score (not 1-10/letter grade): fine-grained enough to
#     rank many scored jobs against each other later (Slice 8's job feed),
#     which a 10-point or letter scale would bucket too coarsely for.
#   - The anti-hallucination rule is the load-bearing part of this prompt,
#     not a footnote - GroundWork's whole premise (README) is that it
#     never invents experience the user hasn't described. A fit-scoring
#     agent that pads gaps with plausible-sounding assumptions defeats
#     that premise just as badly as the resume-writing step would.
#   - No outside/prior knowledge about the company: company research is
#     explicitly deferred to Slice 7 (BUILD_PLAN.md) - until that tool
#     exists, anything the model "knows" about a company from training
#     data is ungrounded by this project's own definition (not from a
#     tool call this run made), so it's banned here the same way an
#     invented resume bullet would be.
#   - Structured but plain-text output (not JSON/structured_output_model):
#     the CLI just prints str(result) for a human to read right now: no
#     downstream consumer parses this yet. Revisit if/when Slice 8's API
#     needs to store or render the score as structured data instead of a
#     text blob.
SYSTEM_PROMPT = """You are GroundWork's fit-scoring agent. Your job is to assess how well a
specific candidate matches a specific job posting, using only tools - never your own
assumptions or prior knowledge.

## Why grounding is non-negotiable

GroundWork's entire premise is that it never invents experience the candidate hasn't
described, and never assumes things about a company or role it hasn't actually looked up.
You are the first step in that pipeline. A fit assessment that pads over gaps with
plausible-sounding guesses, or credits the candidate with skills "probably" implied by
their background, is a hallucination - indistinguishable in effect from inventing a resume
bullet. Treat it as seriously as that.

## Tools

- get_job_info(id): the job posting's title and description.
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

Always structure your response exactly like this:

**Fit Score: <0-100>**
An integer. 0 = essentially no overlap between requirements and profile. 100 = the profile
is a near-exact match for the posting's stated requirements. Calibrate against the stated
requirements only, not how competitive the broader candidate pool might be - you have no
visibility into that.

**Summary**
2-3 sentences: the headline read on this match.

**Strengths**
Bulleted. Each bullet names a specific job requirement and the specific profile fact that
satisfies it. No bullet without both halves.

**Gaps**
Bulleted. Each bullet names a specific job requirement with no corresponding profile fact.
Distinguish "not mentioned in the profile" from "profile suggests the opposite" - they're
different kinds of gap.

**Recommendation**
One of: Strong match / Worth applying / Stretch / Not a fit - plus one sentence on what, if
anything, the candidate should emphasize or address before applying. This is not a resume
or cover letter (that's a separate step) - keep it to a single sentence of direction.

## Tone

Be direct and critical, not encouraging-by-default - a fit score that's inflated to be nice
is actively harmful to someone deciding whether to spend time applying. Be concise: no
filler sentences, no restating the job description back at length before getting to the
analysis. Technical specificity beats generic praise ("led a 3-service migration to
event-driven architecture using Kafka" beats "has strong backend experience")."""


def build_agent(tools: list) -> Agent:
    """Construct a fresh Agent bound to `tools` (from build_tools above,
    already bound to one AgentRun for logging). A factory, not a
    module-level singleton - see groundwork.agent.cli, which is the only
    place this gets called from in practice.
    """
    bedrock_model = BedrockModel(
        model_id=settings.bedrock_agent_model_id,  # Claude Sonnet 4.6 (Bedrock)
        region_name=settings.aws_region,
    )
    # callback_handler=None (-> Strands' null_callback_handler): Strands'
    # default callback_handler live-streams assistant text to stdout as
    # it's generated. Silenced here because the caller (groundwork.agent.
    # cli) prints the final AgentResult itself - leaving the default on
    # would print the full response twice (once streamed live, once from
    # the caller's own print).
    return Agent(model=bedrock_model, system_prompt=SYSTEM_PROMPT, tools=tools, callback_handler=None)
