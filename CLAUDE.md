# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Backend MVP (BUILD_PLAN.md Slices 0-6): job data loaded, profile upload/extraction, a Score Fit agent, a Job Agent (interview/resume/cover-letter/fit-Q&A with AgentCore Memory short-term recall), and a `GET/POST /jobs` + `/jobs/{id}/score` + `/jobs/{id}/agent` API surface. No frontend yet — that's next.

Commands in daily use:
- `docker compose up -d postgres` — local Postgres+pgvector
- `uv run alembic upgrade head` — apply migrations
- `uv run uvicorn jobsentinel.api.main:app --reload --port 8000` — run the API locally
- `uv run pytest -m "not integration"` — default test run (mocked DB/agent calls, no Postgres/Bedrock needed); drop the marker filter to include the real-Bedrock extraction test
- `uv run python -m jobsentinel.agent.score_fit.agent '{"job_id": 182}'` / `jobsentinel.agent.job_agent.agent '{"job_id": 182, "message": "..."}'` — run either agent one-shot from the CLI, no server

## Working with the user (collaboration mode)

The user is using this project to learn production-grade backend engineering, scalable system design, agentic applications, and AWS. Act as a senior engineer mentoring them, not an autopilot:

- Generate repetitive/boilerplate code with heavy explanatory comments (why, not just what) when asked for it, but let the user write the core logic of each feature themselves — don't hand them a finished feature when the point is for them to build it.
- Build in complete, testable **vertical slices**, in the order defined in `BUILD_PLAN.md` — each slice cuts across whatever layers it needs (data/DB/backend/agent/frontend), building only as much of each as that capability requires. Don't build out more of a layer (e.g. the full DB schema, a broad API surface) than the current slice needs, and don't jump ahead to a later slice before the current one is runnable end-to-end on its own.
- `BUILD_PLAN.md` is the source of truth for scope and sequencing; it's written curriculum-style — each slice names the concepts it's meant to teach. Update it if scope or order changes; don't silently drift from it.
- Prefer asking questions and pointing at the relevant concept over just implementing when the user is working through a new piece of a layer themselves.

## What JobSentinel is

An agentic job tracker: the user follows specific companies, JobSentinel polls their ATS job boards daily, and when a relevant posting appears an agent scores fit and then **interviews the user** to tailor a resume/cover letter — it is explicitly designed to never invent experience the user hasn't described. Coverage is intentionally limited to followed companies (ATS APIs are per-company, not a job-market-wide search) — this is a deliberate scope decision, not a gap to fill.

## Architecture (target)

```
React (Vite) ──> Lambda Function URL ──> FastAPI + Mangum ──> AgentCore Runtime
   S3/CF              (one Lambda,          (CRUD, auth)       (Strands agent,
                     all endpoints)              │              tools, Bedrock)
                                                 │                    │
                                                 └──> Supabase <──────┘
                                                      (Postgres + pgvector)

EventBridge Scheduler ──> Poller Lambda ──> ATS APIs ──> Supabase
```

Three deployable units:

| Unit | Runtime | What it does |
|---|---|---|
| API | Lambda + Function URL | All HTTP endpoints (one FastAPI app, Mangum-wrapped) |
| Poller | Lambda + EventBridge | Nightly ATS board polling, plain handler, no FastAPI |
| Agent | AgentCore Runtime | Strands agent + tools, its own container |

**Hard architectural rule:** the API never calls Bedrock directly — only AgentCore Runtime does. The agent never calls the API. Both the API and the agent reach Supabase through a shared data-access module (keep this shared rather than duplicating data access in each unit once it's built).

## Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React 18 + Vite (plain JS, no TypeScript) | No build-step complexity |
| Hosting | S3 + CloudFront | Pennies |
| API | FastAPI + Mangum → Lambda Function URL | 15-min timeout, no API Gateway cost |
| Agent | Strands SDK + AgentCore Runtime + Bedrock | Known ground from FitAgent |
| Model | Claude Sonnet (Bedrock) | Agent loop + analysis |
| Embeddings | Titan Text Embeddings V2 (1024d) | Job/profile matching |
| DB | Supabase Postgres + pgvector | RDS has no scale-to-zero |
| Files | S3, presigned uploads | Resume storage |
| Auth | Clerk | Drop-in React + ~15 lines JWKS verify |
| Secrets | SSM Parameter Store | Free (Secrets Manager is $0.40/secret/mo) |
| Scheduling | EventBridge Scheduler | Nightly poll |

Known tradeoff: Mangum buffers responses, so there's no token streaming from the API — the UI shows progress states instead. If streaming becomes non-negotiable, the plan is to move the API to App Runner (~$5–15/mo) while keeping everything else identical — don't add streaming workarounds to the Lambda+Mangum path itself.

Idle cost target is ~$2–6/mo; only inference scales with usage, which is why token budgets belong in the schema from day one (keep this in mind if/when designing the DB schema).

## Build order

Built as feature-driven **vertical slices**, not one fully-completed architectural layer at a time — see `BUILD_PLAN.md` for the concrete slice sequence. Each slice builds only as much of the data/DB/backend/agent/frontend layers as that specific capability needs, not the full layer up front. The sequence is ordered to reach real agent development and evaluation as early as possible: core agentic capability (fit-scoring, the interview, cover-letter generation) is validated from the CLI before company-following CRUD, a broad API surface, auth, or any frontend work. Each slice should end at something actually runnable — don't start the next slice before the current one is runnable end-to-end on its own.
