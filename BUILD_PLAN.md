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
| Research Company (web search, background tool only — no dedicated UI) | Yes | Multi-source retrieval + reasoning, non-deterministic what it uses |
| Score Fit (job vs. profile) | Yes | Reasoning over retrieved facts, not a fixed formula |
| **Job Agent** — resume tailoring, cover letter, fit Q&A (one agent, one shared session per job) | **Yes — the core feature** | Multi-turn; the agent decides what's missing and when it's done. Originally two separate capabilities (Resume Optimization, Cover Letter); merged into one agent with a shared toolset — see the scope decision below |
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
- **Company following is hardcoded board token(s) for early slices.** Real follow/unfollow CRUD arrives once the core agent loop is validated (Slice 7).
- **Greenhouse only for real ingestion in early slices.** Ashby/Lever exploration is already done (Slice 0); ingestion pollers for them are a later addition, not MVP.
- **Resume/profile extraction is a plain single LLM call, not agentic** — see classification table above.
- **Company research (web search tool) is deferred until after fit-scoring is validated** (Slice 6, not Slice 3) — avoids picking a search API/dealing with its cost and latency before the core loop is proven. It is also never its own user-facing step (see the Job Agent decision below) — purely a background grounding tool for the Score Fit Agent and the Job Agent.
- **Embeddings/pgvector fit-matching is deferred to a stretch slice** (Slice 8). Naive DB lookups (fetch-by-ID, simple filters) are enough while the agent loop itself is being validated — there's no multi-job search need until Slice 7's job feed exists.
- **Minimal real Postgres tables from Slice 1 onward**, not flat-file fixtures — local Postgres is already running (Slice 0). Each slice adds only the columns it needs, not the full schema up front.
- **Resume tailoring, cover letter drafting, and fit Q&A are ONE agent (the "Job Agent"), not three separate agents, and not a master-orchestrator-plus-sub-agents split.** Decided via brainstorming before Slice 5 started. Reasoning: all three share the same job, the same profile, and the same grounding rules, and happen sequentially within one conversation, not in parallel — splitting them into separate agents (or a master agent delegating to sub-agents) would just mean manually relaying context between them that one shared session gives you for free, and none of the three need a distinct persona or isolated scratch-space that would justify the added complexity. The one exception: if Company Research (Slice 6) grows into genuinely multi-step exploration, that specific capability is a reasonable candidate to become a nested agent-as-tool later (an `Agent` call wrapped in a plain `@tool` function — Strands has no dedicated class for this) so its internal search/synthesis mess stays out of the main conversation. Not needed for MVP.
- **The Job Agent is gated behind a successful Score Fit run for that job.** You invest in tailoring only after deciding, via Score Fit, that the job is worth pursuing. Its opening message references the stored score/gaps rather than starting cold (requires a real, queryable "has Score Fit run for job X" record — see Slice 5's gating-requirement bullet, not yet built).
- **Cross-session/cross-job memory (AgentCore Memory) is short-term-per-job + long-term-per-user, not one flat memory.** Short-term memory scoped to `(user, job)` is what lets the Job Agent recall what Score Fit found for *that* job without manual prompt-seeding; long-term memory scoped to the user only is what lets a stated preference ("wants fast-paced startups") surface again in a *different* job's session later. AgentCore Memory informs the agents' own reasoning — it is never the backing store for app/UI logic (e.g. gating), which stays in Postgres.

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
- [x] Write `scripts/load_jobs.py`, the one-off loading script (reuses `explore_greenhouse.fetch_jobs`) that pulls one company's board and upserts postings into `jobs` — a basic upsert is fine; idempotency/backoff/scheduling is **not** required yet, that's Slice 7's productionized poller
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
- [x] Designed & wrote the `profiles` table migration **(design exercise)** — one JSONB `data` column holding `ExtractedProfile.model_dump()` whole (`id`, `data`, `created_at`), not normalized per-section tables or flat `category`/`fact_text` rows. **Append-only history, not a singleton**: every submission inserts a new row with a new `id` rather than overwriting one row in place, so past resume versions stay queryable instead of being discarded. No `updated_at` - rows are never modified after insert. Still single-user for now ("no real multi-tenant auth yet" is still the locked-in scope); a `user_id` column arrives with Slice 9's real users, to scope "latest" per user
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

- [x] Add `strands-agents`, `boto3` to `pyproject.toml`
- [x] Confirm local AWS credentials have Bedrock model access for Claude Sonnet — Claude Sonnet 5 itself is still pending account-level Bedrock model access (see `Settings.bedrock_agent_model_id`); running on Claude Sonnet 4.6 in the meantime, same access path, swap the id back once granted
- [x] Write Alembic migration for `agent_runs` (`id`, `job_id`, `started_at`, `ended_at`, `outcome`, `input_tokens`, `output_tokens`, `cost_usd`) — token/cost accounting lives on the run record from the start, per the stack's "token budgets in the schema from day one" principle, without a separate table yet
- [x] Write Alembic migration for `tool_calls` (`id`, `run_id`, `tool_name`, `args`, `result`, `created_at`) — generated in the same migration as `agent_runs` (both added to `db/models.py` together), reviewed before applying
- [x] Implement tool `get_job(job_id)` — wraps Slice 1's `get_job` (named `get_job_info` in `groundwork/agent/main.py`)
- [x] Implement tool `query_profile_facts()` — wraps `groundwork.db.profile.get_latest_profile` (added back alongside Slice 2's now-id-scoped `get_profile(id)`, since the agent needs "the current profile" with no id in hand)
- [x] Wire both into a Strands `Agent` with a system prompt: score fit between the job and the profile, cite only what the tools returned, produce a score + written rationale **(design exercise — the prompt/scoring logic is the actual point of this slice)** — an initial version was hand-written; the full production prompt in `groundwork/agent/main.py`'s `SYSTEM_PROMPT` (0-100 score, grounding rules, fixed output sections) was written by Claude at explicit request to move the slice along faster, not as a self-directed design exercise — worth a closer read/iteration pass later even though it's tested and working
- [x] Write a CLI entrypoint, e.g. `python -m groundwork.agent.cli score <job_id>` — `groundwork/agent/cli.py`
- [x] Log every tool call to `tool_calls`, every run to `agent_runs` — `groundwork/db/agent_runs.py` (`start_run`/`end_run`/`log_tool_call`), tool calls logged from inside each tool in `main.py`'s `build_tools()`
- [x] Manually run it against Slice 1's test job + your real profile facts; check the rationale isn't citing anything the tools didn't return — ran `python -m groundwork.agent.cli score 182`: both tools called exactly once (verified directly in `tool_calls`), grounded rationale referencing specifics from the real job posting and profile, token usage + estimated cost recorded on the `agent_runs` row
- [x] **Iteration pass on the output format** (flagged above as worth revisiting): replaced the free-text markdown output (`**Fit Score: N**` + prose sections) with a validated schema, `groundwork/agent/schema.py`'s `FitAssessment` (`summary`, `strengths`, `gaps`, `match`, `recommendation_note`), forced via Strands' `structured_output_model` on the `Agent` — same tool-forced-schema mechanism Slice 2's `extract_profile` already uses via raw Bedrock Converse, just routed through Strands. Two decisions made via discussion before writing this:
  - **Dropped the numeric `fit_score` (0-100) entirely, replaced by a 5-value `Match` enum** (`strong_match` / `good_match` / `potential_match` / `weak_match` / `not_a_match`), each with a written definition in `MATCH_DEFINITIONS` that's interpolated into `SYSTEM_PROMPT` (single source, not duplicated prompt text). Reasoning: a holistic 0-100 ask is uncalibrated LLM-as-judge output — no real arithmetic behind it, drifts run-to-run — and a numeric fit_score would need either (a) the model to also freely pick a category, risking incoherent pairs like "92 / stretch," or (b) code-side thresholds mapping score→category, which is more machinery than a direct 5-value categorical judgment buys given the score's own calibration problem. A rubric'd category is still an LLM holistic judgment, not a true calculation — the further step (classify each requirement met/partial/not-met, compute the category deterministically in code) was discussed and deliberately deferred, not forgotten.
  - **`match` declared last in the schema, after `strengths`/`gaps`** — Strands fills structured-output fields in schema order, so the model writes out evidence before committing to a category, preserving the same "don't guess cold" anchoring the old prompt got from asking for prose before a score.
  - `gaps` distinguishes `gap_type` (`not_mentioned` / `contradicts` / `posting_underspecified`) rather than one flat bullet list, since "profile is silent" and "profile suggests the opposite" (and "the posting itself didn't say enough") are different situations needing different follow-up.
  - Added `agent_runs.result` (JSONB, migration `0ef692aa42a3`) storing `FitAssessment.model_dump()` on success — this is what makes the assessment queryable by field for the Slice 5 Job Agent and eventual UI, instead of re-parsing response text. `agent_runs.outcome` stays a short status string only.
  - Verified against job 182 again post-change: structured output validated, persisted, and queryable (`result->'match'`, `jsonb_array_length(result->'gaps')`) directly in Postgres.

## Slice 4 — Agent evaluation harness

Goal: a repeatable way to test agent behavior across multiple job/profile pairs, not just eyeballing one run.

*Teaches:* building an evaluation harness for a non-deterministic system; hallucination detection as an explicit, checkable test target.

- [x] Pick 3-5 real postings across different roles/companies (via the Slice 0 exploration scripts) and load them with Slice 1's loader — went with roles only, not companies: `scripts/eval_score_fit.py`'s `FIXTURE_JOB_IDS` picks 5 postings off the already-loaded Anthropic board, chosen to span match categories on purpose (a clear skills-domain mismatch, a seniority-only mismatch, an ambiguous customer-facing role, etc.) rather than real company diversity — revisit if cross-company differences (posting style/length, ATS quirks) turn out to matter once a second board is loaded
- [x] Write an eval script that runs Slice 3's `score` against each fixture job + your profile, printing results side by side — `scripts/eval_score_fit.py`, calls `groundwork.agent.score_fit.agent.invoke()` directly per fixture and prints a summary table plus full strengths/gaps detail per job
- [x] Write assertions against `tool_calls`/`agent_runs` (e.g. "both tools were called exactly once," "no call had empty args"), not exact model output text **(design exercise — note: implemented by Claude at the user's explicit request, not written by the user — see this slice's note below)** — `scripts/eval_score_fit.py`'s `check_run()` checks: each tool called exactly once, `get_job_info` called with no args (would only be non-empty if its closure binding regressed), neither tool's result is an error, and the run recorded `outcome="success"`/a `result`/a `cost_usd`. All 5 fixtures pass.
- [x] Manually review several runs for hallucination — does the rationale ever cite something not in your actual profile facts or the job text? This is the real test of the anti-hallucination design goal. — reviewed full strengths/gaps output across 3 independent runs of all 5 fixtures: every strength's evidence traces to a named project/employer/cert, gap_type usage (not_mentioned/contradicts/posting_underspecified) is used correctly and consistently, and the Account Executive fixture (job 1, deliberately picked as a hard domain-mismatch test) correctly scored `not_a_match` without inventing transferable sales skills. Match categories were stable across all 3 runs. One residual gap: every fixture skews weak_match/not_a_match because the profile is junior relative to Anthropic's mostly senior postings — a true strong_match/good_match case has never been exercised, so that calibration direction is still unverified.
- [x] Iterate on Slice 3's prompt/tools based on what you find before moving on — one real fix came out of building `check_run()`, not the hallucination review: `get_job_info(job_id)` in `groundwork/agent/score_fit/agent.py` took the job id as a model-supplied tool argument rather than a closure-bound one, the exact bug class already found and fixed in the Job Agent's `get_job_info` earlier this slice. It hadn't misfired across any fixture run, but nothing structurally prevented it. Fixed to match `profile_id`'s existing closure-bound pattern: `build_tools` now takes `job_id` as a parameter, `get_job_info()` takes no arguments, and `check_run()` asserts its logged args are always empty as a regression guard.

## Slice 5 — Job Agent: resume tailoring, cover letter, and fit Q&A (one agent, shared session)

Goal: one continuous agent — the "Job Agent" — that a user talks to about a specific job: it identifies gaps between profile and job, asks targeted questions, drafts a tailored resume and/or cover letter as text, and can answer open-ended questions about the fit — all in one session, routed by the model itself rather than by separate UI flows per capability.

*Teaches:* agent-decided control flow/termination, stateless multi-turn design over HTTP, session-scoped agent memory design, and recognizing when a capability split calls for one agent with more tools vs. genuinely separate agents.

Originally planned as two separate slices/agents (an interview → tailored-resume agent, then a cover-letter agent reusing the pattern); merged into one Job Agent via brainstorming before this slice started — see the locked-in scope decision above ("one Job Agent, not three, not a master-orchestrator-plus-sub-agents split") for the full reasoning.

- [x] **Gating requirement (do this first):** the Job Agent requires a successful Score Fit run to exist for this job before it's usable. Today nothing distinguishes *which capability* an `agent_runs` row was for, and the actual score isn't stored anywhere queryable (`outcome` is just `"success"`/`"error: ..."` text) — add whatever's needed to answer "has Score Fit run successfully for job X (for the current profile)" as a real query, not a re-run. Options: a `kind`/`capability` column on `agent_runs`, and/or a small table storing the score itself (or fold into Slice 7's `documents` table) **(design exercise — pick the shape)** — went with a `kind` column (`score_fit`/`job_agent`) on `agent_runs`, per `groundwork.db.agent_runs`'s `KIND_SCORE_FIT`/`KIND_JOB_AGENT` + `get_latest_successful_result`; the Job Agent's `invoke()` (`groundwork/agent/job_agent/agent.py`) checks this before doing anything else
- [x] Decide whether Postgres owns the Job Agent's turn-by-turn conversation log at all, or whether AgentCore short-term memory (below) replaces it — don't duplicate the same history in two systems. If Postgres does own it, generalize the originally-planned `interview_turns` table (`id`, `job_id`, `role` [agent/user], `content`, `created_at`) since it's no longer resume-specific **(design exercise)** — Postgres owned it temporarily (`job_agent_turns`, reloaded into a fresh `Agent` on every turn) so the Job Agent was testable before Memory existed. **Revisited and removed**: table dropped (`alembic downgrade` + deleted `334f6baf1117_create_job_agent_turns_table.py`), `groundwork/db/job_agent_turns.py` deleted, and `invoke()` no longer reloads/persists turns — every call is single-turn until the short-term tier below is wired in to replace it. See `job_agent/agent.py`'s module docstring for the TODO.
- [ ] Wire up **AgentCore Memory**, two tiers:
  - **Short-term**, scoped to `(actor_id=user, session_id=job-{job_id})` — lets the Job Agent recall what the Score Fit Agent already found for this job with no manual "seed the prompt" plumbing, and keeps resume/cover-letter/Q&A continuous within one job's conversation. Scoped per job so different jobs' sessions never bleed into each other.
  - **Long-term**, scoped to `actor_id` only (no job/session scoping) — durable, cross-job facts about the user surfaced during conversation (stated preferences like "wants fast-paced startups," "likes Rust, dislikes C"), available to every future session for that user. Populated via an extraction strategy over conversation transcripts (likely async, post-session) — **the extraction step needs the same anti-hallucination discipline as the live agent**: a single passing mention must not become a generalized trait.
  - AgentCore Memory is the agent's semantic recall, not a replacement for the Postgres rows above — the UI's "has Score Fit run" gating stays backed by a real row, never derived from a memory query.
- [ ] Implement tool `record_answer` — persists a user's answer as a new profile fact, `source="interview"` **(design exercise)** — originally implemented via `groundwork.db.profile.add_interview_note` into `ExtractedProfile.interview_notes`, tagged with the `job_id` the conversation happened in. **Removed** along with `job_agent_turns` above (same revisit) — `InterviewNote`/`ExtractedProfile.interview_notes` deleted from `groundwork/extraction/schema.py`, `add_interview_note` deleted from `groundwork/db/profile.py`. Re-implement as a tool that writes through AgentCore Memory's long-term tier once that client exists, not back into the profile row.
- [x] Implement tool `mark_interview_complete` (or equivalent) — the agent calls this itself when it's done gathering what it needs; the only thing that ends that phase of the loop **(design exercise)**
- [x] Extend the Job Agent: given a job + profile (+ short-term memory of anything Score Fit already found), identify gaps, ask targeted questions, only draft resume/cover-letter text once it has enough — **hard rule: no fixed turn count in code** — "short-term memory of Score Fit" is the `get_fit_assessment` tool reading the Postgres row directly, not AgentCore Memory (still not wired up)
- [x] Implement the tailored-resume-rewrite capability: text output only, grounded in profile facts old and new **(design exercise)** — no separate tool/endpoint: SYSTEM_PROMPT's control-flow rule directs the model to draft this as plain conversational text once it has enough grounding, consistent with the "one agent, not three" scope decision
- [x] Implement the cover-letter-generation capability, grounded in profile facts + job text (no company research yet — that's Slice 6) — reusing the same gap-analysis/session rather than a separate flow **(design exercise — how much to reuse vs. build fresh per capability)** — same mechanism as the resume rewrite above, no dedicated code path
- [x] Give the Job Agent a way to just answer questions about the fit/gaps (reading the stored Score Fit result) without necessarily drafting anything — the "or anything else" part of the toolset — `get_fit_assessment` tool + SYSTEM_PROMPT rule 6
- [ ] `POST /jobs/{id}/agent` (or similar) — start/continue a turn with the Job Agent (calls the agent core directly, never Bedrock from the API layer)
- [ ] `GET /jobs/{id}/agent` — fetch conversation history
- [ ] Manually run a full session end-to-end: ask for resume help, then cover-letter help, then a fit question, all in one conversation with no restart; confirm it asks reasonable questions, stops on its own, and nothing drafted invents facts not in the profile/job text
- [ ] Manually confirm long-term memory works across jobs: state a preference in one job's session, start a session for a *different* job, confirm the Job Agent recalls (and cites) it without being told again

## Slice 6 — Company research tool (web search)

Goal: add live company/product context now that the core loop is proven — a background tool, not a user-facing feature of its own.

*Teaches:* when/why to add an external tool to an agent, and the cost/latency tradeoffs of doing so.

- [ ] Choose a web-search mechanism (e.g. a Bedrock-integrated search tool, or a third-party API) **(open decision — revisit vendor choice when you get here, don't guess now)**
- [ ] Implement tool `research_company(company_name)` wrapping that search
- [ ] Wire it into the Score Fit Agent's (Slice 3) and Job Agent's (Slice 5) toolsets as an additional grounding source — **no dedicated endpoint or UI panel of its own**; it's exposed to the user only through the effect it has on Score Fit's rationale and the Job Agent's output, the same way `get_job_info`/`get_profile_facts` already work
- [ ] Log its tool calls like any other tool; re-run Slice 4's eval fixtures and check whether the added context actually improves rationale/output quality or just adds noise/cost

## Slice 7 — Company following, job feed, productionized poller, first UI

Goal: the app becomes usable end-to-end for one real user, not just testable from a CLI.

*Teaches:* idempotent ingestion (upsert vs. insert, backoff/rate-limit handling), consuming an async/agentic backend from a UI.

- [ ] Design & write a `companies` table migration (name, board token, source) **(design exercise)**
- [ ] `POST/GET/DELETE /companies` — follow/list/unfollow
- [ ] Implement the board-token inference heuristic from the README: try common slug variants against each ATS's known URL pattern, HTTP-check for a 200, fall back to asking the user to paste the token — **plain deterministic logic, not an agent tool**
- [ ] Productionize Slice 1's loader into a real poller: idempotent upsert, dedupe by external ID, backoff/retry on rate limits, diffing so only new/changed postings surface
- [ ] `GET /jobs` — list jobs, filtered by followed companies + `positions.py`'s canonical-position matching
- [ ] Design & write a `documents` table migration to persist generated resumes/cover letters, versioned per job — first point where generated text is actually stored, not just returned
- [ ] `GET /jobs/{id}/documents`
- [ ] Scaffold the frontend (`npm create vite@latest frontend -- --template react`, plain JS): job feed, per-job **Score Fit** button (always enabled, no gating) and **Work with Job Agent** button (disabled until a successful Score Fit run exists for that job, per Slice 5's gating requirement), a way to read results. Opening the Job Agent should show a first message referencing the stored score/gaps, not a cold greeting. Company Research (Slice 6) has no button/panel anywhere in this UI.
- [ ] Run the full flow through the UI against the local API end-to-end

## Slice 8 — Stretch capabilities

*Teaches:* vector search fundamentals, hybrid retrieval — and recognizing when it's actually needed vs. premature.

- [ ] Mock Interview & Prep Agent: new agent flow asking common + role-specific questions, giving feedback, suggesting homework — standalone/on-demand, not gated behind Score Fit and not part of the per-job Job Agent flow **(design exercise)**
- [ ] **Conversational job-query agent**: a new agent (or tool-extension of an existing one) that answers natural-language questions over the job feed — "what's the best fit for me right now?", "show me FDE roles" — by calling read-only tools (`list_jobs` w/ filters reusing `positions.py`'s canonical-position matching, `get_fit_scores`) rather than a fixed UI query form. **(design exercise — decide whether this is a new agent or a tool added to an existing one, and how "best fit" ranks across jobs given Slice 3's categorical `Match` enum has no natural sort order)**. Depends on Slice 7's job feed existing; naturally pairs with this slice's pgvector work below if ranking needs semantic similarity rather than just filtering by category/position.
- [ ] Save/track applied jobs + basic analytics
- [ ] Embeddings & pgvector: swap the naive job/profile lookups for real vector similarity search once there's more than one job to meaningfully search across

## Slice 9 — Hardening & scale-out

*Teaches:* authn vs. authz, least-privilege IAM, serverless deployment tradeoffs, the production-ops layer that's easy to skip and expensive to skip later.

- [ ] Clerk auth + multi-user row scoping
- [ ] Broaden the API surface/validation as needed for real usage
- [ ] AWS deployment: Lambda+Mangum for the API, AgentCore Runtime for the agent, EventBridge-scheduled Lambda for the poller, S3+CloudFront for the frontend, SSM for secrets
- [ ] Structured logging, retries/backoff, token-budget enforcement, cost monitoring
