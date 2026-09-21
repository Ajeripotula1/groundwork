"""Structured output for the fit-scoring agent (BUILD_PLAN.md Slice 3).

Replaces an earlier free-text markdown output (a "**Fit Score: N**" header
plus prose sections) with a validated schema, for two reasons: (1) a
holistic 0-100 number turned out to be uncalibrated LLM-as-judge vibes, not
a real calculation - see the design discussion that led here - and (2) the
whole point of dropping this onto `agent_runs` (see jobsentinel.db.agent_runs)
is for other agents (the Slice 5 Job Agent) and the eventual UI to consume
this by field, not by re-parsing prose.

Strands forces this shape via `structured_output_model` on the Agent
(jobsentinel.agent.score_fit.agent.build_agent) - same tool-forced-schema
mechanism as jobsentinel.extraction.extract's Bedrock Converse call, just
routed through Strands instead of a raw boto3 client.

Lives under `jobsentinel.agent.shared` (not inside score_fit/ or job_agent/)
because both agents' independent AgentCore Runtime deployments import it -
score_fit's `structured_output_model` and job_agent's `get_fit_assessment`
tool both need the same Match/FitAssessment shape, and each agent directory
is its own deployable container (see jobsentinel/agent/__init__.py).
"""

from enum import Enum

from pydantic import BaseModel


class Match(str, Enum):
    """How well the candidate's profile aligns with the job posting.

    Deliberately the agent's *only* categorical output - an earlier design
    paired this with a numeric fit_score (0-100), but a free-floating number
    turned out to be uncalibrated (drifts run-to-run, no real arithmetic
    behind it) without buying anything a 5-value category doesn't already
    give the UI/downstream agents. MATCH_DEFINITIONS below is what actually
    disciplines the model's judgment - see SYSTEM_PROMPT in both
    jobsentinel.agent.score_fit.agent and jobsentinel.agent.job_agent.agent,
    each built from this same dict so the prompt text and this enum's
    meaning never drift apart between the two agents.
    """

    STRONG_MATCH = "strong_match"
    GOOD_MATCH = "good_match"
    POTENTIAL_MATCH = "potential_match"
    WEAK_MATCH = "weak_match"
    NOT_A_MATCH = "not_a_match"


# Single source of truth for what each Match value means - interpolated into
# both agents' SYSTEM_PROMPT (jobsentinel.agent.score_fit.agent and
# jobsentinel.agent.job_agent.agent) so the model is told exactly this,
# and kept here so any other reader (a future UI tooltip, another engineer)
# sees the identical definition instead of a second hand-typed copy that can
# drift from what the model was actually told.
MATCH_DEFINITIONS: dict[Match, str] = {
    Match.STRONG_MATCH: "Meets essentially all important requirements; profile aligns closely with the role.",
    Match.GOOD_MATCH: "Meets most important requirements but has some non-critical gaps.",
    Match.POTENTIAL_MATCH: "Relevant foundation, but meaningful gaps exist; reasonable stretch.",
    Match.WEAK_MATCH: "Some overlap, but several important requirements are missing.",
    Match.NOT_A_MATCH: "Major incompatibility or a hard requirement prevents meaningful fit.",
}


class GapType(str, Enum):
    """Why a requirement isn't a Strength - these are different situations
    with different remediation paths, so collapsing them into one flat
    "gap" bullet (as the earlier markdown format did) would lose the
    distinction the system prompt already asks the model to make.
    """

    NOT_MENTIONED = "not_mentioned"  # profile is silent on this requirement
    CONTRADICTS = "contradicts"  # profile suggests the opposite
    POSTING_UNDERSPECIFIED = "posting_underspecified"  # job text didn't say enough to judge


class Strength(BaseModel):
    """One job requirement the profile satisfies, and the specific profile
    fact that satisfies it - no bullet without both halves, per
    SYSTEM_PROMPT's grounding rules.
    """

    requirement: str
    evidence: str


class Gap(BaseModel):
    """One job requirement without a corresponding profile fact."""

    requirement: str
    gap_type: GapType
    note: str | None = None


class FitAssessment(BaseModel):
    """Full structured output of one fit-scoring run."""

    summary: str
    strengths: list[Strength]
    gaps: list[Gap]
    # Declared last on purpose: Strands fills structured-output fields in
    # schema order, so the model writes out strengths/gaps evidence before
    # it has to commit to a category - the same "don't let it guess cold"
    # anchoring the old prompt got from asking for a written rationale
    # before the numeric score.
    match: Match
    # What to emphasize or address before applying - separate from `match`
    # itself: `match` is a description of the fit as it stands, this is the
    # one sentence of actionable direction. Not a resume or cover letter
    # (that's Slice 5's Job Agent) - keep it to one sentence.
    recommendation_note: str
