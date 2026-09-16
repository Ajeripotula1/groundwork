"""Agent Entry point file
This file contains the implementation for all the Agents capabilities:
    1. Research Company: analyze the posting entry from DB and also additional websearch tool to learn more about the company, project, or role
    2. Score Fit: be able to analyze and understand the job, compare it againsts user profile (generated from user's resume)
    3. Resume Optimization: Work with user to identify strenghts, weaknesses, and WORK with user (interactive interview still chat) to bridge those gaps, rewrite points, or suggest changes. This prevents hallucination, and encourages personalized touch to resume. The end result is a resume rewritten with user's changes and presented to user via text (don't need to worry about genreating and formatting files yet)
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
from groundwork.db.profile import get_latest_profile

settings = get_settings()


def build_tools(run_id: int) -> list:
    """Bind get_job_info/get_profile_facts to one AgentRun so every call
    logs itself to `tool_calls` (BUILD_PLAN.md Slice 3: "Log every tool
    call to tool_calls") - see groundwork.db.agent_runs.log_tool_call. A
    factory, not module-level tools, because run_id differs per
    invocation - see build_agent below.
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
        Retrieve the current profile (the most recently submitted resume's
        structured facts) to compare against jobs.

        Returns:
            profile: The profile data as a JSON str, or an error message if
            no profile has been submitted yet.
        """
        # No id param (unlike the original version) - single-user MVP, so
        # "the profile" is just the most recent submission. This also
        # matches BUILD_PLAN.md's tool signature (`query_profile_facts()`,
        # no args) and lets the CLI take just a job_id, not a profile id
        # the caller has to already know. See groundwork.db.profile.
        # get_latest_profile's docstring for the "most recent row is the
        # current profile" reasoning; get_profile(id) still exists
        # separately for fetching a specific historical snapshot.
        engine = get_engine()
        profile = get_latest_profile(engine)
        if profile is None:
            result = {"error": "no profile has been submitted yet"}
        else:
            result = {"profile": profile["data"]}
        log_tool_call(engine, run_id, "get_profile_facts", {}, result)
        return json.dumps(result)

    return [get_job_info, get_profile_facts]


SYSTEM_PROMPT = """You are a useful Job Agent that helps user's analyze Jobs and prepare. You will use tools to get
specific informaiton related to job postings, and the user. You will use these tools to analyze the job against the user's profile.
Return a comprehensive analysis of the user's fit for the following Job.

Here are the tools avaialble to you
get_profile_facts: get the user's information
get_job_info: get the job posting information

Use ONLY these tools to get the relevant information and base your analysis ONLY on these tools output.
Be concise, critical and technical if needed.
"""


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
    return Agent(model=bedrock_model, system_prompt=SYSTEM_PROMPT, tools=tools)
