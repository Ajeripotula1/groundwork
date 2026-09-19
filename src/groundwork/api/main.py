"""
FastAPI application entrypoint.

This is the API unit from CLAUDE.md's three-deployable-units architecture:
in production it's Mangum-wrapped behind a Lambda Function URL (that
wrapping is a later, deployment-slice concern); locally it just runs under
uvicorn. Per the hard architectural rule, this app never calls Bedrock
directly and - once Slice 3 exists - never reaches into the agent's tools
either; it only ever calls into groundwork.db and groundwork.agent's public
functions. Routers should stay thin: request in, call a data-access/agent
function, response out.

Run locally:
    uvicorn groundwork.api.main:app --reload --port 8000

Then, e.g.:
    curl http://localhost:8000/health
"""

from fastapi import FastAPI

from groundwork.api.routers import jobs, profile

app = FastAPI(title="GroundWork API")

app.include_router(profile.router)
app.include_router(jobs.router)


@app.get("/health")
def health() -> dict:
    """Trivial liveness check - confirms the app boots and answers requests
    at all, independent of whether any specific router's dependencies (a
    DB connection, Bedrock access, etc.) are actually working yet."""
    return {"status": "ok"}
