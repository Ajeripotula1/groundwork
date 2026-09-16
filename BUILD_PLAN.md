# GroundWork Build Plan

This is the source of truth for **what** we're building, **in what order**, and the **concrete steps** to get there. It's written curriculum-style: each slice names the concepts it's meant to teach, not just the deliverable. Checkboxes track progress — check one off as it's actually done (`- [ ]` → `- [x]`), don't batch-check ahead of the code. Update this file if scope, order, or tasks change — don't let it silently drift from what's actually being built.

A task marked **(design exercise — you write this)** is intentionally left unspecified: figuring it out is the point of the slice, not scaffolding. Everything else is infra/plumbing concrete enough to just execute.

## Methodology: vertical slices, not full layers

As of 2026-09-13 this replaced an earlier layer-by-layer plan (fully build the data layer, then the agent, then the backend, then the frontend). That order was inefficient here specifically because we don't know what data/schema/backend the agent actually needs until we've built and tested it.

Instead: each slice is a small, complete, testable capability that cuts across whatever layers it needs — data, DB, backend, agent, frontend — building only as much of each as that capability requires, not the full layer. No slice starts until the previous one is runnable and testable on its own. The sequence is ordered to reach real agent development and evaluation as early as possible; conventional CRUD/infra work (company following, a broad API surface, auth, deployment, hardening) comes after the core agentic loop is validated, not before.

This still means clean architecture and no unnecessary rework — see the hard architectural rules in `CLAUDE.md`/`README.md` (API never calls Bedrock directly, agent never calls the API, shared data-access module). Building incrementally doesn't mean building sloppily; it means not building more of a layer than the current slice needs yet.

## Feature classification (from README's Key Features)

| Capability | Agentic? | Why |
|---|---|---|
| Research Company (web search + DB posting → synthesis) | Yes | Multi-source retrieval + reasoning, non-deterministic what it uses |
| Score Fit (job vs. profile) | Yes | Reasoning over retrieved facts, not a fixed formula |
| Resume Optimization (interview → tailored rewrite) | **Yes — the core feature** | Multi-turn; the agent decides what's missing and when it's done |
| Cover Letter (same interview pattern) | Yes | Same mechanism, different output |
| [Stretch] Mock Interview & Prep Agent | Yes | Multi-turn, adaptive to answers |
| Company following (add/remove board token) | No | Plain CRUD |
| Job polling & ingestion | No | Scheduled fetch + upsert, deterministic |
| Board-token inference ("try to infer... with logic") | No | A slug-guessing heuristic against known ATS URL patterns — deliberately not an LLM call |
| Job feed display + position filtering | No | Already built (`positions.py`) — deterministic alias matching |
| Save/track/analytics [stretch] | No | CRUD + aggregation |
| Resume/profile extraction from an uploaded resume | No (by decision) | A single structured-extraction LLM call — a utility step, not the agent. The interview is where genuine agent behavior on the profile begins. |

## Scope decisions (locked in for MVP)

- **Single-user.** No real multi-tenant auth yet. Clerk is a late slice.
- **Resume input is a PDF upload** (`POST /profile/upload`, Slice 2) — PDF text is extracted server-side via `pypdf` and fed into the extraction utility. No OCR/scanned-image support - a PDF with no text layer is a clear 422, not a silent empty extraction. (A raw-text `POST /profile` existed briefly alongside it; removed once PDF upload covered real usage and the raw-text HTTP route had no user-facing purpose left. `extract_profile()` itself still takes plain text directly - that's what `tests/test_extract_profile.py` calls.)
- **Company following is hardcoded board token(s) for early slices.** Real follow/unfollow CRUD arrives once the core agent loop is validated (Slice 8).
- **Greenhouse only for real ingestion in early slices.** Ashby/Lever exploration is already done (Slice 0); ingestion pollers for them are a later addition, not MVP.
- **Resume/profile extraction is a plain single LLM call, not agentic** — see classification table above.
- **Company research (web search tool) is deferred until after fit-scoring is validated** (Slice 7, not Slice 3) — avoids picking a search API/dealing with its cost and latency before the core loop is proven.
- **Embeddings/pgvector fit-matching is deferred to a stretch slice** (Slice 9). Naive DB lookups (fetch-by-ID, simple filters) are enough while the agent loop itself is being validated — there's no multi-job search need until Slice 8's job feed exists.
- **Minimal real Postgres tables from Slice 1 onward**, not flat-file fixtures — local Postgres is already running (Slice 0). Each slice adds only the columns it needs, not the full schema up front.

---

## Slice 0 — Foundation (done)

*Teaches:* monorepo/package layout, 12-factor config, reading a third-party API's real shape before designing a schema against assumptions, recognizing structural differences across similar-but-not-identical APIs.

- [x] Package scaffolding, `pyproject.toml`, local Postgres+pgvector via `docker-compose.yml`, `groundwork.config.Settings`, smoke test
- [x] `scripts/explore_greenhouse.py`, `scripts/explore_asby.py`, `scripts/explore_lever.py` — raw data pulled and inspected against live boards for all three ATS's
- [x] `scripts/positions.py` — `CANONICAL_POSITIONS` alias map + title-variance-aware filtering, reused unmodified across all three ATS scripts

## Slice 1 — Job data the agent can read (done)

Goal: at least one real job posting's text is durably queryable, via a data-access function the agent will call directly in Slice 3.

*Teaches:* building only the schema a specific capability needs (not the full previously-planned 6-table schema up front), the shared data-access module pattern.

- [x] Normalize job-description extraction across all three ATS's before touching the DB: `scripts/job_text.py` (shared `html_to_text`/`clean_whitespace`/`normalized_job`/`summarize_jobs`) used by `explore_greenhouse.py` (HTML `content` field), `explore_asby.py` (plain `descriptionPlain` field), and `explore_lever.py` (combines `descriptionPlain` with the `lists` array, where Lever actually puts requirements/skills) — all three now produce the identical shape: `ats_job_id`, `source`, `board_token`, `title`, `description`, `url`, `fetched_at`, `raw_json`
- [x] **Switched to SQLAlchemy ORM + Alembic autogenerate** (was hand-written Core `Table` + hand-written migrations) — a deliberate tradeoff to spend less time on schema/migration mechanics and more on agent code. `groundwork/db/models.py`'s `Job` model (SQLAlchemy 2.0 `Mapped[...]`/`mapped_column` style) is now the single source of truth for the schema; `migrations/env.py`'s `target_metadata` points at `Base.metadata` so `alembic revision --autogenerate` can diff against it. Data-access functions still hand callers plain dicts, not live ORM objects — see `groundwork/db/jobs.py`'s `get_job` docstring for why (avoids the classic `DetachedInstanceError` footgun). Upserts still go through a Core-style `INSERT ... ON CONFLICT`, since the ORM has no native atomic upsert — standard even in ORM-first codebases.
- [x] `Job` model mirrors the normalized shape: `id`, `ats_job_id`, `source`, `board_token`, `title`, `description`, `url`, `raw_json` (JSONB), `fetched_at`, plus a `UNIQUE (source, ats_job_id)` constraint as the real dedupe key
- [x] Write `groundwork/db/jobs.py`: `upsert_job` (`INSERT ... ON CONFLICT (source, ats_job_id) DO UPDATE`, returns the internal `id`), `get_job(job_id)` — this is the shared module the agent calls directly in Slice 3 (never through the API — see the hard architectural rule)
- [x] Write `scripts/load_jobs.py`, the one-off loading script (reuses `explore_greenhouse.fetch_jobs`) that pulls one company's board and upserts postings into `jobs` — a basic upsert is fine; idempotency/backoff/scheduling is **not** required yet, that's Slice 8's productionized poller
- [x] Fixed a pre-existing scaffolding bug found while testing this: `.env`'s `DATABASE_URL` used a bare `postgresql://` scheme, which SQLAlchemy resolves to the psycopg2 dialect by default — but this project installs psycopg3 (`psycopg[binary]`). Every DB call would have failed with `ModuleNotFoundError: No module named 'psycopg2'` regardless of Slice. Fixed to `postgresql+psycopg://` in both `.env` and `.env.example`.
- [x] Declared `requests`/`beautifulsoup4` as real `pyproject.toml` dependencies (used by the exploration/loading scripts, previously only installed ad hoc)
- [x] Verified: `Job` model + `upsert_job`'s generated SQL both build correctly (checked the compiled `INSERT ... ON CONFLICT ... RETURNING` statement directly), and `alembic revision --autogenerate` gets all the way through model/metadata resolution before failing — only on the DB connection itself
- [x] `docker compose up -d`, `alembic revision --autogenerate -m "create jobs table"`, `alembic upgrade head`, `python scripts/load_jobs.py anthropic` — all run successfully
- [x] Confirmed rows landed: 594 rows in `jobs` from Anthropic's Greenhouse board
- [x] Fixed test case for Slices 2-4: **job `id = 182`** — "Full-Stack Software Engineer, Reinforcement Learning" (`ats_job_id 5186067008`, ~10.3k-character description)

## Slice 2 — Profile ingestion (resume → structured facts)

Goal: submit resume text over HTTP, get back structured facts, durably stored.

*Teaches:* the line between a utility LLM call and an agent, first FastAPI surface, request validation basics.

- [x] Added `fastapi`/`uvicorn` to `pyproject.toml` (Mangum/Lambda wrapping stays deferred to the deployment slice), plus `httpx2` as a dev dependency (needed by FastAPI's `TestClient`)
- [x] `groundwork/api/main.py` — the FastAPI app instance + a `/health` liveness check, with a `groundwork/api/routers/` package so each resource (profile now; jobs/interview/companies in later slices) gets its own router instead of main.py accumulating route handlers directly
- [x] `groundwork/api/routers/profile.py` — `POST /profile/upload` (PDF) routed, functional, and persisted; `GET /profile` returns the stored profile or `404` if nothing's been submitted yet. (A raw-text `POST /profile` existed briefly too - removed once PDF upload covered real usage and it had no remaining user-facing purpose; `extract_profile()` is still callable directly with plain text, which is what `tests/test_extract_profile.py` and the fixture files use.) Verified booting for real via `uvicorn` (not just `TestClient`) and hit all endpoints with `curl`.
- [x] Designed `groundwork/extraction/schema.py`'s `ExtractedProfile` (nested `Education`/`WorkExperience`/`Project`/`Certification` + flat `skills: list[str]`) **(design exercise)** — richer than the flat `profile_facts` shape originally sketched here; storage (next item) was designed against this shape instead
- [x] Designed & wrote the `profiles` table migration **(design exercise)** — one JSONB `data` column holding `ExtractedProfile.model_dump()` whole (`id`, `data`, `created_at`), not normalized per-section tables or flat `category`/`fact_text` rows. **Append-only history, not a singleton**: every submission inserts a new row with a new `id` rather than overwriting one row in place, so past resume versions stay queryable instead of being discarded. No `updated_at` - rows are never modified after insert. Still single-user for now ("no real multi-tenant auth yet" is still the locked-in scope); a `user_id` column arrives with Slice 10's real users, to scope "latest" per user
- [x] Ran the migration (`alembic revision --autogenerate -m "add profiles table"` → reviewed → `alembic upgrade head`; a follow-up migration dropped `updated_at` once the append-only design replaced the original singleton-row idea)
- [x] Wrote `groundwork/db/profile.py`: `insert_profile` (plain Postgres `INSERT ... RETURNING`, one new row per call) and `get_latest_profile` (most recent row by `id`)
- [x] Wrote the resume-extraction utility (`groundwork/extraction/extract.py`): one Bedrock Converse call (Claude Haiku 4.5, not Sonnet — bounded structured extraction doesn't need Sonnet-tier reasoning, see the model-choice discussion) forcing tool-use against `ExtractedProfile`'s JSON schema **(design exercise — this is a plain utility call: single request/response, no tool loop)**
- [x] Added PDF upload support (`groundwork/extraction/pdf.py`, `pypdf`) — `POST /profile/upload` extracts text server-side, feeds it through the extraction utility; scope extended from the original "raw text only" decision once actually needed. Once this covered real usage, the parallel raw-text `POST /profile` route was removed as redundant (see scope decision above) - `POST /profile/upload` is now the only submit route
- [x] Wired `GET /profile` (returns the latest submission) and persistence into `POST /profile/upload`
- [x] Ran locally via `uvicorn`; POST'd two different resumes in a row, confirmed both persisted as separate rows in Postgres (verified via `psql` directly - distinct `id`s, both `data` blobs intact) and `GET /profile` returned the most recent one
- [x] Unit tests for both remaining endpoints' wiring (`tests/test_profile_endpoint.py`) — extractor AND DB layer (`insert_profile`/`get_latest_profile`) both mocked, so these run with no Postgres up at all; request validation, PDF content-type/unreadable-PDF handling, 404-when-empty, two submissions produce two inserts (not one update)
- [x] Wrote a test for the extraction utility itself (`tests/test_extract_profile.py`, marked `integration`, excluded from the default `pytest -m "not integration"` run) — hits real Bedrock against the fixture resume, loose content-level assertions (e.g. "skills contains Python"), plus an explicit anti-hallucination check that `summary` stays `None` since the fixture resume has no summary section

## Slice 3 — Core agent: fit-score one job against a profile

This is the first real agent. It has to read as one — the model decides what to do, grounded only in tool results — not a fixed sequence with an LLM call inside.

*Teaches:* agent loop / tool-calling design, grounding responses in retrieved data instead of the model's own claims, deterministic testing of a non-deterministic system.

- [ ] Add `strands-agents`, `boto3` to `pyproject.toml`
- [ ] Confirm local AWS credentials have Bedrock model access for Claude Sonnet
- [ ] Write Alembic migration for `agent_runs` (`id`, `job_id`, `started_at`, `ended_at`, `outcome`, `input_tokens`, `output_tokens`, `cost_usd`) — token/cost accounting lives on the run record from the start, per the stack's "token budgets in the schema from day one" principle, without a separate table yet
- [ ] Write Alembic migration for `tool_calls` (`id`, `run_id`, `tool_name`, `args`, `result`, `created_at`)
- [ ] Implement tool `get_job(job_id)` — wraps Slice 1's `get_job`
- [ ] Implement tool `query_profile_facts()` — wraps Slice 2's `list_profile_facts`
- [ ] Wire both into a Strands `Agent` with a system prompt: score fit between the job and the profile, cite only what the tools returned, produce a score + written rationale **(design exercise — the prompt/scoring logic is the actual point of this slice)**
- [ ] Write a CLI entrypoint, e.g. `python -m groundwork.agent.cli score <job_id>`
- [ ] Log every tool call to `tool_calls`, every run to `agent_runs`
- [ ] Manually run it against Slice 1's test job + your real profile facts; check the rationale isn't citing anything the tools didn't return

## Slice 4 — Agent evaluation harness

Goal: a repeatable way to test agent behavior across multiple job/profile pairs, not just eyeballing one run.

*Teaches:* building an evaluation harness for a non-deterministic system; hallucination detection as an explicit, checkable test target.

- [ ] Pick 3-5 real postings across different roles/companies (via the Slice 0 exploration scripts) and load them with Slice 1's loader
- [ ] Write an eval script that runs Slice 3's `score` against each fixture job + your profile, printing results side by side
- [ ] Write assertions against `tool_calls`/`agent_runs` (e.g. "both tools were called exactly once," "no call had empty args"), not exact model output text **(design exercise)**
- [ ] Manually review several runs for hallucination — does the rationale ever cite something not in your actual profile facts or the job text? This is the real test of the anti-hallucination design goal.
- [ ] Iterate on Slice 3's prompt/tools based on what you find before moving on

## Slice 5 — Interactive interview → tailored resume text

Goal: the agent identifies gaps between profile and job, asks the user targeted questions, and only then drafts a tailored resume as text.

*Teaches:* agent-decided control flow/termination, stateless multi-turn design over HTTP.

- [ ] Write Alembic migration for `interview_turns` (`id`, `job_id`, `role` [agent/user], `content`, `created_at`)
- [ ] Write `groundwork/db/interview.py`: `insert_interview_turn`, `list_interview_turns`
- [ ] Implement tool `record_answer` — persists a user's answer as a new `profile_facts` row, `source="interview"` **(design exercise)**
- [ ] Implement tool `mark_interview_complete` — the agent calls this itself; the only thing that ends the loop **(design exercise)**
- [ ] Extend the agent: given a job + profile, identify gaps, ask targeted questions, stop only when it calls `mark_interview_complete` — **hard rule: no fixed turn count in code**
- [ ] Implement the tailored-resume-rewrite step once the interview completes: text output only, grounded in profile facts old and new **(design exercise)**
- [ ] `POST /jobs/{id}/interview` — start/continue a turn (calls the agent core directly, never Bedrock from the API layer)
- [ ] `GET /jobs/{id}/interview` — fetch history
- [ ] Manually run a full interview end-to-end via curl/httpx; confirm it asks reasonable questions, stops on its own, and the resume text doesn't invent anything

## Slice 6 — Cover letter generation

Goal: reuse the gap-analysis pattern to produce a cover letter.

*Teaches:* reusing an agent capability for an adjacent output without duplicating the core loop.

- [ ] Decide how much of Slice 5's interview flow to reuse vs. build fresh (e.g. a lighter variant asking only cover-letter-specific questions like "why this company/role") **(design exercise)**
- [ ] Implement the cover-letter-generation step, grounded in profile facts + job text (no company research yet — that's Slice 7)
- [ ] `POST /jobs/{id}/cover-letter` (or extend `/interview` with a mode — your call)
- [ ] Manually run it end-to-end for the same test job; confirm grounding holds

## Slice 7 — Company research tool (web search)

Goal: add live company/product context now that the core loop is proven.

*Teaches:* when/why to add an external tool to an agent, and the cost/latency tradeoffs of doing so.

- [ ] Choose a web-search mechanism (e.g. a Bedrock-integrated search tool, or a third-party API) **(open decision — revisit vendor choice when you get here, don't guess now)**
- [ ] Implement tool `research_company(company_name)` wrapping that search
- [ ] Wire it into Slice 3's fit-scoring prompt and Slice 6's cover-letter prompt as an additional grounding source
- [ ] Log its tool calls like any other tool; re-run Slice 4's eval fixtures and check whether the added context actually improves rationale/cover-letter quality or just adds noise/cost

## Slice 8 — Company following, job feed, productionized poller, first UI

Goal: the app becomes usable end-to-end for one real user, not just testable from a CLI.

*Teaches:* idempotent ingestion (upsert vs. insert, backoff/rate-limit handling), consuming an async/agentic backend from a UI.

- [ ] Design & write a `companies` table migration (name, board token, source) **(design exercise)**
- [ ] `POST/GET/DELETE /companies` — follow/list/unfollow
- [ ] Implement the board-token inference heuristic from the README: try common slug variants against each ATS's known URL pattern, HTTP-check for a 200, fall back to asking the user to paste the token — **plain deterministic logic, not an agent tool**
- [ ] Productionize Slice 1's loader into a real poller: idempotent upsert, dedupe by external ID, backoff/retry on rate limits, diffing so only new/changed postings surface
- [ ] `GET /jobs` — list jobs, filtered by followed companies + `positions.py`'s canonical-position matching
- [ ] Design & write a `documents` table migration to persist generated resumes/cover letters, versioned per job — first point where generated text is actually stored, not just returned
- [ ] `GET /jobs/{id}/documents`
- [ ] Scaffold the frontend (`npm create vite@latest frontend -- --template react`, plain JS): job feed, a way to trigger interview/cover-letter, a way to read results
- [ ] Run the full flow through the UI against the local API end-to-end

## Slice 9 — Stretch capabilities

*Teaches:* vector search fundamentals, hybrid retrieval — and recognizing when it's actually needed vs. premature.

- [ ] Mock Interview & Prep Agent: new agent flow asking common + role-specific questions, giving feedback, suggesting homework **(design exercise)**
- [ ] Save/track applied jobs + basic analytics
- [ ] Embeddings & pgvector: swap the naive job/profile lookups for real vector similarity search once there's more than one job to meaningfully search across

## Slice 10 — Hardening & scale-out

*Teaches:* authn vs. authz, least-privilege IAM, serverless deployment tradeoffs, the production-ops layer that's easy to skip and expensive to skip later.

- [ ] Clerk auth + multi-user row scoping
- [ ] Broaden the API surface/validation as needed for real usage
- [ ] AWS deployment: Lambda+Mangum for the API, AgentCore Runtime for the agent, EventBridge-scheduled Lambda for the poller, S3+CloudFront for the frontend, SSM for secrets
- [ ] Structured logging, retries/backoff, token-budget enforcement, cost monitoring
