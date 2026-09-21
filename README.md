# JobSentinel

An agentic job tracker and assistant for companies you actually care about.

You follow companies. It watches their job boards daily. When something opens, an agent scores your fit, then **interviews you** to tailor your resume and cover letter — it never invents experience you don't have.

---

## Why this exists

Most AI resume tools are one-click slop generators: paste a job, get a hallucinated resume. This one works the other way around. The agent reads the posting, researches the company, identifies what's missing from your background, and then **asks you questions**. It only writes what you actually tell it.

It also doesn't pretend to search the entire job market. Public ATS APIs are per-company, so coverage is an explicit product decision: you follow companies, it tracks them.

---

## Architecture

```
React (Vite) ──> Lambda Function URL ──> FastAPI + Mangum ──> AgentCore Runtime
   S3/CF              (one Lambda,          (CRUD, auth)       (Strands agent,
                     all endpoints)              │              tools, Bedrock)
                                                 │                    │
                                                 └──> Supabase <──────┘
                                                      (Postgres + pgvector)

EventBridge Scheduler ──> Poller Lambda ──> ATS APIs ──> Supabase
```

**Three deployable units:**

| Unit | Runtime | What it does |
|---|---|---|
| API | Lambda + Function URL | All HTTP endpoints (one FastAPI app, Mangum-wrapped) |
| Poller | Lambda + EventBridge | Nightly ATS board polling, plain handler, no FastAPI |
| Agent | AgentCore Runtime | Strands agent + tools, its own container |

The API never calls Bedrock directly — only AgentCore Runtime. The agent never calls the API. Both hit Supabase through a shared data-access module.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React 18 + Vite (plain JS) | No build-step complexity |
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

**Idle cost: ~$2–6/mo.** Only inference scales with usage, which is why token budgets are in the schema from day one.

**Known tradeoff:** Mangum buffers responses — no token streaming. UI shows progress states instead. If streaming becomes non-negotiable, move the API to App Runner (~$5–15/mo); everything else stays identical.

---

## Build order

Built as feature-driven vertical slices (see `BUILD_PLAN.md`), not one fully-completed architectural layer at a time. Each slice builds only as much of the data/backend/agent/frontend layers as that capability needs. Core agentic capability (fit-scoring, the interview, cover-letter generation) gets validated first, from the CLI, before company-following CRUD, a broad API surface, or any frontend work.


## Key Features 

### Company/Job Data Layer:
- Function: pull latest job postings for company ATS tools that user's can access
- Features 
   1. Present users with a a Collection of Companies (and their Job Board Tokens) that they can follow (adding all is an option)
   2. See latest jobs for selected company (that match their desired position)
   3. Can see high level overview of Job and access external Application (from the ATS board) to apply
   4.  [Stretch] Can Save jobs, track applied to jobs, get analytics 
- Implementation: Daily polling for postins for all companies in the provided selection. if user wants to follow a company NOT listed in the default companies list. Try to infer board token self with logic, if not possible have fallback which tells users to make sure comapny has ATS job board, and to paste the board toke/slug. On successful adding, immediatley try to fetch the listings and then add to daily polling list of companies. 

### Agentic Layer
- Function: personalized job Agent that helps you understand and prepare for role to maximize chances
- Features
   1. Research Company: analyze the posting entry from DB and also additional websearch tool to learn more about the company, project, or role
   2. Score Fit: be able to analyze and understand the job, compare it againsts user profile (generated from user's resume)
   3. Resume Optimization: Work with user to identify strenghts, weaknesses, and WORK with user (interactive interview still chat) to bridge those gaps, rewrite points, or suggest changes. This prevents hallucination, and encourages personalized touch to resume. The end result is a resume rewritten with user's changes and presented to user via text (don't need to worry about genreating and formatting files yet)
   4. Cover Letter: Same process, pull from company research, interview user on interests, and generate cover letter content 
   5. [Stretch]: Mock Interivew and Prep Agent that creates sessions where user's are asked common interview questions, job/ role specific questions, and given feedback and bonus homeowork/ research to better prepare 

### Backend Layer 
- Function: facilatate access to Job data, user Data, and Agent as well as allow resume uploading. 
- Features:
   1. Resume/profile submission: accept raw resume text (no file upload/parsing yet — that's a later addition once it's actually needed) and run it through a one-shot LLM extraction call into structured profile facts. This is a plain utility call, not the agent.
   2. Profile access: list/view stored profile facts.
   3. Agent invocation endpoints: start/continue an interview for a given job, trigger cover-letter generation — these call the agent core directly, never Bedrock from the API layer (see architecture rule above).
   4. Job/company access: list jobs (filtered by followed companies + desired position), follow/unfollow a company, fetch generated documents.
   5. Shared data-access module used by both the API and the agent, so SQL isn't duplicated between the two units.

### UI Layer
- Function: Clean, minamalist UI for users to access data, manage their own, and converse with Agent
- Features: Deferred — this is the last layer built (see `BUILD_PLAN.md`'s vertical slices). Early development and testing happens via CLI and direct API calls only; this section gets filled in once we reach the frontend slice.
