"""Resume-extraction utility (BUILD_PLAN.md Slice 2).

A single Bedrock call:
Structured output is done via tool-use, not free-text JSON parsing: Bedrock's
Converse API has no Anthropic-style output_config.format, so instead we
declare one tool whose input schema IS the ExtractedProfile schema, force
the model to call it, and validate the arguments it returns through Pydantic.
"""

import boto3

from groundwork.config import get_settings
from groundwork.extraction.schema import ExtractedProfile

# Deliberately strict about what NOT to do: every clause here exists to
# close off a specific hallucination path (composing a summary, inferring
# dates, categorizing skills, filling in a section that isn't present).
SYSTEM_PROMPT = """You extract structured facts from resume text. You do not \
write, infer, or summarize anything - you only capture what is explicitly \
stated in the text.

Rules:
- Only include a section (education, experience, projects, certifications) \
if the resume actually has one. An empty list is correct when a section \
isn't present - never invent an entry to fill it.
- Copy bullet points close to verbatim from the source text. Do not \
paraphrase, combine, or embellish them.
- Leave a field null/omitted if the resume doesn't state it. Do not guess \
dates, locations, or degree types.
- Only fill in `summary` if the resume has an explicit summary/objective \
statement written by the candidate. Never compose one yourself.
- List skills exactly as named in the resume's skills section, uncategorized.
- Do not infer which skills were used in which role. Only capture what \
each bullet actually says."""


def extract_profile(resume_text: str) -> ExtractedProfile:
    """Run resume_text through the extraction model and return a validated
    ExtractedProfile.

    Raises RuntimeError if the model responds without calling the
    extraction tool (shouldn't happen with tool_choice forced, but Bedrock
    doesn't guarantee it), or ValidationError (from pydantic) if the tool
    arguments don't match the schema.
    """
    settings = get_settings()
    bedrock = boto3.client("bedrock-runtime", region_name=settings.aws_region)

    tool_spec = {
        "toolSpec": {
            "name": "extract_profile",
            "description": "Record the structured facts extracted from the resume text.",
            "inputSchema": {"json": ExtractedProfile.model_json_schema()},
        }
    }

    response = bedrock.converse(
        modelId=settings.bedrock_extraction_model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": resume_text}]}],
        toolConfig={
            "tools": [tool_spec],
            "toolChoice": {"tool": {"name": "extract_profile"}},
        },
    )

    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            # Converse hands back the tool input already parsed as a dict
            # (unlike the raw Anthropic Messages API, which returns a JSON
            # string) - model_validate does the schema check.
            return ExtractedProfile.model_validate(block["toolUse"]["input"])

    raise RuntimeError(
        f"Model did not call extract_profile tool; stop_reason={response['stopReason']!r}"
    )
