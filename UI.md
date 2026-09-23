# UI.md — Frontend build plan (BUILD_PLAN.md Slice 7)

This is the step-by-step implementation plan for the JobSentinel frontend. **You write all the code; this file tells you exactly what to build, with which library/API/endpoint, and how to know it works.** Nothing here requires you to pick a library, a layout, a state strategy, or a file name — those decisions are already made below. If a step feels ambiguous, that's a bug in this doc; flag it.

Conventions used below:
- **Build** = what to write. **Why** = the concept the step teaches. **Done when** = a manual check that proves the step works before you move on.
- Every step ends at something runnable in the browser. Don't start step N+1 until step N's "Done when" passes.
- After every step run `npm run lint` and `npm run build` from `frontend/` — both must pass.
- All paths are relative to `frontend/src/` unless they start with `src/jobsentinel` (backend) or are a repo-root file.

---

## 1. Where things stand (audit of what exists)

| Already done | Missing / needs fixing |
|---|---|
| Vite 8 + React 19 (plain JS), Tailwind v4, shadcn/ui (`base-nova` style, **Base UI primitives — not Radix**), only `button` installed | `frontend/.env.local` doesn't exist → `main.jsx` throws on boot (missing Clerk key) |
| `main.jsx`: `ClerkProvider` → `QueryClientProvider` → `BrowserRouter` | **Backend has no CORS middleware** → browser blocks every call from `localhost:5173` to `localhost:8000` |
| `App.jsx`: routes `/`, `/jobs/:jobId`, `/profile`, `/sign-in/*`, `/sign-up/*` + `ProtectedRoute` | `api/client.js` can't send `FormData` (resume upload) and throws errors with no HTTP status (UI can't tell "404 = not scored yet" from a real failure) |
| `api/client.js` `apiFetch` (attaches Bearer token via an injected `getToken`) | No nav/layout shell; no data hooks; the three pages are `<div>` stubs |
| Backend contract for everything the UI needs (Slice 6 / 6.5) | QueryClient uses defaults → retries failed queries 3× with backoff, which makes *expected* 4xx responses feel broken |

**Base UI gotcha (affects every step):** this project's shadcn components wrap `@base-ui/react`, so there is **no `asChild` prop**. To render a router `<Link>` that looks like a button, apply `buttonVariants(...)` (exported from `components/ui/button.jsx`) as the `className` of the `<Link>`. Never nest `<Button>` inside `<Link>`. Compound components (Tabs, etc.) use `value` / `onValueChange` — after `npm run ui -- add <name>`, open the generated file in `components/ui/` to confirm exported names before using them.

---

## 2. Decisions already made (veto any of these now, not mid-build)

1. **Server state = TanStack Query v5 only.** `useState` is reserved for purely local UI state: filter text, chat draft, active tab, copied-flag.
2. **Never send `profile_id`.** Every endpoint resolves "the caller's latest profile" when it's omitted. Consequence: `GET /profile` returns no `id`, so after a new resume upload the old score and chat history no longer apply → the upload mutation must invalidate the `score` and `agent` caches (Step 3).
3. **"Expected 404" is data, not an error.** `useProfile` and `useScoreFit` catch `ApiError` status 404 in their `queryFn` and return `null`. So `data === null` means "none yet"; `data === undefined` means "still loading"; `isError` means a real failure.
4. **Score Fit has two calls:** `GET /jobs/{id}/score` (cached, read on page load) and `POST /jobs/{id}/score` (always a fresh, billed agent run, only on button click). The POST result is written straight into the GET's cache.
5. **Job Agent chat is gated on `useScoreFit(jobId).data` being non-null** — never by sending a message and reading the backend's gate text (that comes back as a normal 200 `reply`, indistinguishable from an agent message).
6. **Chat cache is written by the send mutation, not refetched.** The history query has `staleTime: Infinity` and `refetchOnWindowFocus: false`; the send mutation appends `{user, assistant}` turns via `setQueryData`. (History is read from AgentCore Memory; refetching right after a write risks a stale read that would drop the newest turn.)
7. **Agent replies render as Markdown** (`react-markdown` + `@tailwindcss/typography`) with a copy-to-clipboard button — drafted resumes/cover letters are the product.
8. **Job Detail layout:** posting on the left, a two-tab panel (Fit score | Job Agent) on the right at `lg`+, stacked below `lg`.
9. **Route visibility (updated 2026-09-21):** `/` (home) and `/jobs`, `/jobs/:jobId` are **public** — reachable and functional (job list/detail data needs no auth on the backend) while signed out. `/profile` stays a **fully protected route** — hard redirect to sign-in via `ProtectedRoute` — because there's no signed-out-meaningful content there (every profile endpoint requires a Bearer token, and there's nothing to show without the signed-in user's own resume).
10. **Signed-out access to a job's fit score / Job Agent chat is blocked inline, not by a route redirect** (decided explicitly: the user should land on the job and see the posting, not bounce to sign-in before seeing anything). On `/jobs/:jobId`, when `useAuth().isSignedIn` is false, the fit-score/chat panel is replaced with a "sign in to see your fit score" prompt instead of rendering `ScoreFitPanel`/the chat tab; the hook driving that check (`useScoreFit`) is passed `enabled: isSignedIn` so it never fires a request that's certain to 401. Same reasoning for the "upload your resume" banner on the job list (`useProfile({ enabled: isSignedIn })`).
11. **Explicitly not in this slice:** pagination or server-side filtering, per-job score badges on the list (no bulk score endpoint), profile-history UI, streaming, dark-mode toggle, toast library, form library, automated frontend tests (manual walkthrough in Step 6 is the test), deployment.

---

## 3. Backend contract (the only endpoints the UI calls)

Base URL: `import.meta.env.VITE_API_BASE_URL` (already read in `api/client.js`). "Bearer" = Clerk session token in `Authorization`, attached by `apiFetch`. Errors are `{"detail": "<string>"}`, except FastAPI request-validation 422s where `detail` is an array of `{msg, ...}`.

| Method + path | Auth | Request | Success | Statuses the UI must handle |
|---|---|---|---|---|
| `GET /jobs` | none | — | `200` `JobSummary[]`: `id, title, source, board_token, url (nullable), fetched_at (ISO)` — ~594 rows, ordered by id | — |
| `GET /jobs/{id}` | none | — | `200` `JobDetail` = `JobSummary` + `ats_job_id, description` (plain text with `\n` line breaks) | `404` unknown job |
| `GET /profile` | Bearer | — | `200` `ExtractedProfile` (no `id` field) | `404` = user has no profile yet |
| `POST /profile/upload` | Bearer | `multipart/form-data`, field name **`file`** | `201` `ExtractedProfile` | `415` not a PDF, `422` unreadable / no text layer (message in `detail`) |
| `GET /jobs/{id}/score` | Bearer | — | `200` `FitAssessment` | `404` = never scored **or** user has no profile |
| `POST /jobs/{id}/score` | Bearer | no body | `200` `FitAssessment` (fresh run, takes seconds) | `404` unknown job, `422` no profile (message in `detail`) |
| `GET /jobs/{id}/agent` | Bearer | — | `200` `[{role, text}]`, oldest first; `[]` if no profile or no messages | `404` unknown job |
| `POST /jobs/{id}/agent` | Bearer | JSON `{"message": "<non-empty>"}` | `200` `{reply: string}` (multi-second, plain/markdown text) | `404` unknown job |

Response shapes:
- **`FitAssessment`**: `summary: string`; `strengths: [{requirement, evidence}]`; `gaps: [{requirement, gap_type, note: string|null}]` where `gap_type ∈ not_mentioned | contradicts | posting_underspecified`; `match ∈ strong_match | good_match | potential_match | weak_match | not_a_match`; `recommendation_note: string`.
- **`ExtractedProfile`**: `contact {name, email, phone, location, links[]}` (all nullable except `links`); `summary: string|null`; `education [{institution, degree, location, dates, details[]}]`; `experience [{company, title, location, dates, bullets[]}]`; `projects [{name, dates, bullets[], technologies[], url}]`; `certifications [{name, issuer, date}]`; `skills: string[]`. Every list can be empty; every non-identifier string can be `null`.
- Job Agent `role` values come from Strands messages — expected `"user"` / `"assistant"`. Confirm in the Network tab in Step 5; the plan treats any role other than `"user"` as the assistant.

---

## 4. Target file layout (final state)

```
frontend/src/
  api/client.js                     (modify: ApiError, FormData, network errors)
  hooks/
    useApi.js                       (bind Clerk getToken → apiFetch)
    queryKeys.js                    (single source of query-key spelling)
    useJobs.js                      (useJobs, useJob)
    useProfile.js                   (useProfile, useUploadProfile)
    useScoreFit.js                  (useScoreFit, useRunScoreFit)
    useJobAgent.js                  (useJobAgentHistory, useSendJobAgentMessage)
  lib/
    utils.js                        (exists: cn)
    format.js                       (formatDate)
    match.js                        (MATCH_META, GAP_TYPE_LABELS)
  components/
    AppLayout.jsx                   (header + nav + <Outlet/>)
    ProtectedRoute.jsx              (exists)
    ErrorAlert.jsx
    jobs/JobsTable.jsx
    jobs/FitAssessmentView.jsx
    jobs/ScoreFitPanel.jsx
    jobs/JobAgentChat.jsx
    jobs/ChatMessage.jsx
    profile/ProfileUpload.jsx
    profile/ProfileView.jsx
    ui/                             (shadcn-generated; never hand-edit beyond need)
  pages/
    HomePage.jsx  JobListPage.jsx  JobDetailPage.jsx  ProfilePage.jsx  NotFoundPage.jsx
  App.jsx  main.jsx  index.css
```

State map — what lives where:

| State | Home | Key / mechanism |
|---|---|---|
| Job list, job detail | TanStack Query | `['jobs']`, `['job', id]` |
| Current profile (or `null`) | TanStack Query | `['profile']` |
| Score result (or `null`) per job | TanStack Query | `['score', id]` |
| Chat history per job | TanStack Query | `['agent', id]` |
| Scoring in flight / message in flight | Mutation state | `mutation.isPending`, `.variables`, `.error` |
| Title filter text | `useState` in `JobListPage` | — |
| Chat draft | `useState` in `JobAgentChat` | — |
| Active tab | `useState` in `JobDetail` | derived fallback (Step 5) |
| "Copied" flag | `useState` in `ChatMessage` | — |
| Signed-in user / token | Clerk | `useAuth()`, `<UserButton/>` |
| Signed-in status for inline gating (job score/chat, list banner) | Clerk | `useAuth().isSignedIn` — see Decisions 9–10 |

**TanStack Query v5 reminders** (you'll hit these): `useQuery` takes a single options object; `isPending` = "no data yet" (v4's `isLoading` semantics changed); there are **no `onSuccess/onError` callbacks on `useQuery`** in v5 — derive UI from `data`/`error` instead; mutations do still have them; `gcTime` replaced `cacheTime`.

---

## Step 0 — Prerequisites: env, CORS, services (≈20 min)

**Why:** a frontend can't be verified against a backend that browsers refuse to talk to. This step also closes BUILD_PLAN's last open Slice 6.5 item once Step 3 succeeds. Teaches: same-origin policy, CORS preflight, why a Bearer-header API needs `Access-Control-Allow-Headers: authorization`.

**Build:**
1. Create `frontend/.env.local` (gitignored via `*.local`) from `.env.example`:
   - `VITE_CLERK_PUBLISHABLE_KEY` = the publishable key (`pk_test_…`) from the Clerk dashboard → API Keys. It **must be the same Clerk application** whose Frontend API URL is already in the repo-root `.env` as `CLERK_ISSUER`, otherwise the backend rejects every token with 401.
   - `VITE_API_BASE_URL=http://localhost:8000`.
2. Backend CORS — `src/jobsentinel/config.py`: add a `Settings` field `cors_allow_origins: list[str]` defaulting to `["http://localhost:5173"]` (document it like the neighbouring fields; in AWS it would come from an env var as a JSON list, e.g. `CORS_ALLOW_ORIGINS='["https://your-domain"]'`).
3. Backend CORS — `src/jobsentinel/api/main.py`: `app.add_middleware(CORSMiddleware, ...)` (from `fastapi.middleware.cors`) with `allow_origins=get_settings().cors_allow_origins`, `allow_methods=["*"]`, `allow_headers=["*"]`. **Do not** set `allow_credentials` — auth is a Bearer header, not cookies, and credentials + wildcard headers has stricter rules you don't need. Add a short docstring/comment on *why* (browser preflight for the `Authorization` header). Note: when this deploys behind a Lambda Function URL, that URL's own CORS config takes over — deferred to the deployment slice, don't configure both then.
4. (Recommended) Add one test in `tests/test_jobs_endpoints.py` using the existing `TestClient` pattern: send `OPTIONS /jobs` with headers `Origin: http://localhost:5173`, `Access-Control-Request-Method: GET`, `Access-Control-Request-Headers: authorization`; assert `200` and that `access-control-allow-origin` echoes the origin.
5. Confirm `BEDROCK_AGENT_MEMORY_ID` is set in the repo-root `.env` (needed in Step 5; without it `GET/POST /jobs/{id}/agent` return 500). Confirm you still have a Clerk sign-in method enabled (email or Google) in the dashboard. **Test users don't need real inboxes:** on a Clerk *development* instance, any email with a `+clerk_test` subaddress (e.g. `alice+clerk_test@example.com`, `bob+clerk_test@example.com`) skips real email delivery — when asked for the verification code, enter `424242`. Use these for every extra user in Steps 3, 4 and 6. (Fallbacks: Gmail plus-addressing like `you+u2@gmail.com` lands in your one inbox; or create users directly in the Clerk dashboard → Users → Create user.)
6. Start everything, in three terminals: `docker compose up -d postgres` then `uv run uvicorn jobsentinel.api.main:app --reload --port 8000`; and `cd frontend && npm run dev`.

**Done when:**
- `curl -i -X OPTIONS localhost:8000/jobs -H 'Origin: http://localhost:5173' -H 'Access-Control-Request-Method: GET' -H 'Access-Control-Request-Headers: authorization'` returns `200` with an `access-control-allow-origin` header.
- `curl localhost:8000/jobs | head -c 300` returns job JSON.
- `http://localhost:5173/` redirects to Clerk's sign-in, and you can sign up a user (you'll land on the stub "Job list" page).
- `uv run pytest -m "not integration"` still passes.

---

## Step 1 — Foundation: API client, auth-bound hook, query defaults, app shell

**Why:** every later step assumes these five pieces. Teaches: custom error classes carrying HTTP status, why `FormData` must never get a hand-set `Content-Type`, closure-binding an auth token into a reusable hook, layout routes with `<Outlet/>`, the "retry only what can succeed" query policy.

**Build:**

1. **Install deps and shadcn components** (from `frontend/`):
   - `npm install react-markdown @tailwindcss/typography`
   - `npm run ui -- add card badge input table tabs skeleton alert textarea` (use `npm run ui`, not `npx shadcn` — see BUILD_PLAN Slice 7's note on the `EALLOWSCRIPTS` bug).
   - In `index.css`, directly after the existing `@import` lines, add `@plugin "@tailwindcss/typography";` (Tailwind v4 registers plugins in CSS, not a config file).
   - Install icons you'll use from `lucide-react` (already a dependency; no install): `Loader2`, `ArrowLeft`, `ExternalLink`, `CheckCircle2`, `AlertCircle`, `RefreshCw`, `SendHorizontal`, `Copy`, `Check`.

2. **Harden `api/client.js`** (keep the existing `apiFetch` signature):
   - Export `class ApiError extends Error` with `status` (number) and `detail` (string); `message` = `detail`.
   - On a non-`ok` response: `await response.json().catch(() => null)`. `detail` = `body.detail` if it's a string; if it's an array (FastAPI validation error), join each item's `msg` with `"; "`; otherwise fall back to `response.statusText`. Throw `new ApiError(response.status, detail)`.
   - Wrap the `fetch` call: if it *rejects* (server down, CORS failure, offline) throw `new ApiError(0, "Can't reach the server. Check that the API is running.")`.
   - Body handling: if `body instanceof FormData`, pass it through as-is and set **no** `Content-Type` (the browser must generate the `multipart/form-data; boundary=…` header itself). Otherwise keep the current JSON behavior.

3. **`hooks/useApi.js`** — `useApi()`: calls Clerk's `useAuth()` for `getToken` and returns a memoized (`useCallback`, dep `[getToken]`) function `(path, options) => apiFetch(path, { ...options, getToken })`. Every data hook calls `const api = useApi()`. (This is why `apiFetch` takes `getToken` as an argument — tokens are only available inside React.)

4. **`hooks/queryKeys.js`** — export one `queryKeys` object: `jobs` → `['jobs']`; `job(id)` → `['job', id]`; `profile` → `['profile']`; `score(id)` → `['score', id]`; `agent(id)` → `['agent', id]`. `id` is always a **number** (never the raw route string — `['job', 182]` ≠ `['job', '182']`). The first element of `score`/`agent` keys is deliberately a stable prefix so `invalidateQueries({ queryKey: ['score'] })` hits every job.

5. **QueryClient defaults in `main.jsx`**: `new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2 } } })`. Leave mutations at their default (**no retry** — agent calls cost tokens and aren't idempotent).

6. **`components/ErrorAlert.jsx`** — props: `error` (Error or null/undefined), `title` (default `"Something went wrong"`), `onRetry` (optional). Returns `null` if no `error`. Otherwise shadcn `Alert variant="destructive"` with `AlertTitle`, `AlertDescription={error.message}`, and — only if `onRetry` — an outline `Button size="sm"` "Try again". Used by every page/panel below.

7. **App shell.** `AppLayout` now wraps *every* page, signed in or not — it's the nav chrome, not an auth gate. `ProtectedRoute` shrinks to guarding the one route with no signed-out-meaningful content (`/profile` — see Decision 9). The job list/detail routes render for everyone; they gate specific *panels* inline in Steps 3–5, not at the route level.

   - `components/AppLayout.jsx`: `<header className="sticky top-0 z-10 border-b bg-background">` containing a `div` `mx-auto flex h-14 max-w-7xl items-center gap-6 px-4`:
     - Brand `Link to="/"` ("JobSentinel", `font-semibold`) — this **is** the Home link, there's no separate "Home" nav item.
     - `NavLink to="/jobs"` "Jobs" and `NavLink to="/profile"` "Profile" (use `NavLink`'s `className={({isActive}) => …}`: active → `text-foreground`, inactive → `text-muted-foreground hover:text-foreground`). Both links always render, regardless of auth state — clicking "Profile" signed out is what triggers `ProtectedRoute`'s redirect.
     - `<div className="ml-auto flex items-center gap-2">` holding the auth affordance: Clerk's `<SignedIn><UserButton /></SignedIn>` and, in `<SignedOut>`, two links — `Link to="/sign-in"` styled `buttonVariants({ variant: 'ghost', size: 'sm' })` "Sign in" and `Link to="/sign-up"` styled `buttonVariants({ size: 'sm' })` "Sign up". Plain `Link`s, not `SignInButton`'s modal mode — this app uses routed `/sign-in`, `/sign-up` pages (App.jsx below), not a popup.
     - Below the header: `<main className="mx-auto max-w-7xl px-4 py-6"><Outlet /></main>`.
   - `pages/HomePage.jsx` — public, minimal hero for the MVP (no data fetching, no hooks). `<div className="mx-auto max-w-2xl py-16 text-center">`: `h1` "Track job fit without the guesswork" (`text-4xl font-semibold tracking-tight`); a muted paragraph (1–2 sentences: JobSentinel follows specific companies' job boards, scores your fit against a posting, and helps you tailor a resume/cover letter for it — grounded only in what you've actually told it, never invented). Below that, a `flex justify-center gap-3` button row: `Link to="/jobs"` styled `buttonVariants({ size: 'lg' })` "Browse jobs" (always shown); then, `<SignedOut>` `Link to="/sign-up"` styled `buttonVariants({ variant: 'outline', size: 'lg' })` "Get started", `<SignedIn>` `Link to="/profile"` styled the same "Upload your resume" — so the second button is always the sensible next step for whoever's looking at it.
   - `pages/NotFoundPage.jsx`: centered "Page not found" + a `Link` styled with `buttonVariants({ variant: 'outline' })` back to `/`.
   - Refactor `App.jsx` — **one pathless layout route with no auth wrapper**, `<Route element={<AppLayout />}>`, whose children are: `index` → `HomePage`, `jobs` → `JobListPage`, `jobs/:jobId` → `JobDetailPage`, `profile` → `<ProtectedRoute><ProfilePage /></ProtectedRoute>` (the *only* remaining use of `ProtectedRoute` — it wraps just that one element, not the layout), and `*` → `NotFoundPage` (nested here, not as a top-level route, so the header still shows on a typo'd URL). Keep `/sign-in/*` and `/sign-up/*` as top-level routes outside the layout, each wrapped in `<div className="flex min-h-screen items-center justify-center">` (no header on auth pages — nothing to navigate to yet).

**Done when:** `/` renders the hero **signed out**, with no redirect. Header shows "Sign in"/"Sign up" signed out, `UserButton` signed in, on every page including `/`. `/jobs` loads signed out (still a stub page from Step 1 — real data in Step 2). `/profile` signed out redirects to `/sign-in`; signed in it shows the stub page. `/nope` shows Not Found *with the header still visible*. Sign out from `UserButton` while on `/jobs` → you stay on `/jobs` (no redirect — only `/profile` redirects). Lint + build pass. (The `ApiError`/`FormData` paths get exercised in Steps 2–3.)

---

## Step 2 — Jobs list (first real data on screen)

**Why:** the smallest vertical slice that proves the whole pipeline — Clerk token → `apiFetch` → CORS → FastAPI → Postgres → React Query cache → UI. Teaches: `useQuery`, the loading/error/success triad, `staleTime`, derived data with `useMemo` (don't store filtered results in state).

**Build:**
1. `lib/format.js` — `formatDate(iso)`: `new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(iso))`.
2. `hooks/useJobs.js` — `useJobs()`: `useQuery({ queryKey: queryKeys.jobs, queryFn: () => api('/jobs'), staleTime: 5 * 60_000 })` (the list only changes when someone runs the loader script).
3. `components/jobs/JobsTable.jsx` — props `jobs`, `filter` (only used for the empty-message text). shadcn `Table`. Columns: **Title** (`<Link to={`/jobs/${job.id}`} className="font-medium hover:underline">`), **Company** (`Badge variant="secondary"` showing `board_token`), **Source** (plain text, `hidden md:table-cell`), **Fetched** (`formatDate(job.fetched_at)`, `hidden sm:table-cell`). If `jobs` is empty, render one full-width row: `No jobs match "{filter}"`. Row key = `job.id`.
4. `pages/JobListPage.jsx`:
   - `const { data: jobs, isPending, isError, error, refetch } = useJobs()`; `const [filter, setFilter] = useState('')`.
   - `filtered = useMemo(() => jobs?.filter(j => j.title.toLowerCase().includes(filter.trim().toLowerCase())) ?? [], [jobs, filter])`. Plain `includes` on title only; 623 rows needs no debounce, `useDeferredValue`, or pagination.
   - Layout `space-y-4`: `h1` "Jobs" (`text-2xl font-semibold`); muted line `Showing {filtered.length} of {jobs.length}` (only when loaded); shadcn `Input` (`type="search"`, `placeholder="Filter by title…"`, `aria-label="Filter jobs by title"`, `className="max-w-sm"`).
   - `isPending` → 8 `Skeleton` rows (`h-10 w-full`); `isError` → `<ErrorAlert error={error} onRetry={refetch} />`; else `<JobsTable />`.

**As built (2026-09-22) — deviates from the spec above in a few small ways, noted here so this doesn't silently drift:**
- Single `components/JobsTable.jsx`, not `components/jobs/JobsTable.jsx` — no `jobs/` subfolder yet since it's the only jobs-specific component so far; revisit the subfolder once `ScoreFitPanel`/`JobAgentChat` land in Step 5 and there's more than one file to group.
- `JobsTable` owns `useJobs()` and the `filter` state itself (self-contained) rather than `JobListPage` fetching/filtering and passing `jobs`/`filter` down as props. `JobListPage` is just a thin wrapper. Fine at this size; if a second consumer of the same data ever needs the list (e.g. a dashboard widget), lift the query back up to the page then rather than duplicating it.
- Columns actually shipped: **Title** (link), **Company** (plain text, `board_token` — not yet the real `jobs.company` display name, see the deferred DB note above), **Source** (`Badge variant="outline"`, not Company), **Last synced** (not "Fetched" — named for what `fetched_at` actually is; see the deferred `fetched_at`/`posted_at` note above), plus a distinct "no jobs loaded at all" vs. "no jobs match your search" empty state (spec only had the latter).
- Errors render via the already-built `components/ErrorAlert.jsx` (`error`/`title`/`onRetry` props, exactly as Step 1 spec'd it) rather than a hand-rolled `Alert`.
- No `refetch`/"Try again" wired up yet on this page — `ErrorAlert` supports `onRetry` but `JobsTable` doesn't pass one. Worth adding when this page next gets touched.

**Done when:**
- Table shows ~623 jobs; typing "engineer" narrows the count live; clearing restores all.
- Network tab: exactly one `GET /jobs`; navigating to Profile and back within 5 min does **not** refetch.
- **Sign out and reload `/jobs` directly** (public route — Decision 9): the table still loads. `GET /jobs` still succeeds with no `Authorization` header this time (it's a public endpoint — `apiFetch` just omits the header when `getToken()` returns nothing signed out).
- Clicking a title goes to `/jobs/182` (still a stub).
- Stop uvicorn, hard-reload → `ErrorAlert` reads "Can't reach the server…"; restart uvicorn, reload → table loads again (proves the `ApiError(0, …)` path didn't hang the UI; no retry button yet, see deviation note above).

---

## Step 3 — Profile: upload a resume, view extracted facts

**Why:** scoring needs a profile, so this comes before Job Detail. Teaches: `useMutation`, multipart upload from a file input, writing a mutation result into the query cache (`setQueryData`), cross-query invalidation, the "`null` means none yet" pattern.

**Build:**
1. `hooks/useProfile.js`:
   - `useProfile({ enabled = true } = {})`: `queryKey: queryKeys.profile`; `queryFn` calls `api('/profile')` inside try/catch — if the caught error is an `ApiError` with `status === 404`, `return null`; rethrow anything else. Pass `enabled` straight through to `useQuery`'s options. Default `true` so `ProfilePage` (Step 3, always signed in — it's behind `ProtectedRoute`) can keep calling `useProfile()` with no args; `JobListPage`'s banner (below) is what actually needs `enabled: isSignedIn`, since that page is public now (Decision 9).
   - `useUploadProfile()`: `const queryClient = useQueryClient()`; `mutationFn: (file) => { build a FormData, append('file', file), return api('/profile/upload', { method: 'POST', body: formData }) }`; **hook-level** `onSuccess(profile)`: `queryClient.setQueryData(queryKeys.profile, profile)`, then `queryClient.invalidateQueries({ queryKey: ['score'] })` and `invalidateQueries({ queryKey: ['agent'] })`. Put these in the hook's `onSuccess`, not in `mutate(file, { onSuccess })` — call-level callbacks are dropped if the component unmounts mid-upload (user navigates away), hook-level ones still run. *Why invalidate:* see Decision 2.
2. `components/profile/ProfileUpload.jsx` — prop `hasProfile` (boolean). shadcn `Card`: `CardTitle` "Resume", `CardDescription` "Upload a PDF. Text-based PDFs only — scanned images aren't supported." Inside: a hidden `<input type="file" accept="application/pdf" className="hidden">` held in a `useRef`; a `Button` whose `onClick` calls `inputRef.current.click()`, label `hasProfile ? "Upload a new version" : "Upload resume"`. The input's `onChange`: `const file = e.target.files?.[0]`; if present call `upload.mutate(file)`; then reset `e.target.value = ''` so re-selecting the same file re-triggers `onChange`. While `upload.isPending`: button `disabled`, shows spinning `Loader2` (`animate-spin`) + "Extracting your profile…". Below: `<ErrorAlert error={upload.error} title="Upload failed" />` (the server's 415/422 `detail` strings are already user-readable). No client-side type check — `accept` plus the server's 415 is enough.
3. `components/profile/ProfileView.jsx` — prop `profile`. Internal helper component `Section({ title, children })` (a `Card` with a `CardHeader`/`CardTitle` + `CardContent`) to avoid repeating markup. Render, **skipping any section whose array is empty**:
   - **Header card**: `contact.name` as `h2` (fallback "Your profile"); a muted line of `[email, phone, location].filter(Boolean).join(' · ')`; each `contact.links` as `<a target="_blank" rel="noreferrer" className="break-all text-sm underline">`; `summary` as a paragraph if non-null.
   - **Experience**: per entry — `title` · `company` (`font-medium`), muted `[location, dates].filter(Boolean).join(' · ')`, `bullets` as `<ul className="list-disc space-y-1 pl-5 text-sm">`.
   - **Projects**: name (link if `url`), dates, bullets, `technologies` as `Badge variant="outline"` in a `flex flex-wrap gap-1.5` row.
   - **Education**: `institution`, `degree`, `[location, dates]`, `details` as a bullet list.
   - **Certifications**: `name`, muted `[issuer, date]`.
   - **Skills**: `Badge variant="secondary"` per skill in `flex flex-wrap gap-1.5`.
   - Use `key={index}` in these lists (they're read-only and never reordered).
4. `pages/ProfilePage.jsx` — `const { data: profile, isPending, isError, error, refetch } = useProfile()`. Layout `mx-auto max-w-3xl space-y-6`: `h1` "Your profile"; `<ProfileUpload hasProfile={profile != null} />`; then `isPending` → 3 `Skeleton` blocks; `isError` → `ErrorAlert` with retry; `profile === null` → muted paragraph "No resume yet — upload one above."; else `<ProfileView profile={profile} />`. Note the old profile stays visible during a re-upload (the mutation doesn't touch the query until success).
5. **Job list banner (three states, public page — Decision 9/10)** — in `JobListPage`, `const { isSignedIn } = useAuth()` (from `@clerk/clerk-react`) and `const profile = useProfile({ enabled: isSignedIn })`. Render, above the table, a default-variant `Alert` only in these two cases (no banner once a profile exists):
     - `!isSignedIn` → title "Sign in to score jobs against your resume", with a `Link to="/sign-in"` styled `buttonVariants({ size: 'sm' })` "Sign in".
     - `isSignedIn && profile.data === null` (strict equality — `undefined` means still loading, so no flash) → title "Upload your resume to score jobs", with a `Link to="/profile"` styled `buttonVariants({ size: 'sm' })` "Upload resume".

**Done when:**
- Upload your resume PDF → spinner → profile renders (contact, experience, skills…). Hard-refresh → still there (`GET /profile` from Postgres, not client state).
- In the file picker choose "All files" and pick a PNG → red alert with the server's 415 message; a scanned/no-text PDF → the 422 message.
- Sign up a second user in an incognito window (use `bob+clerk_test@example.com`, code `424242` — see Step 0): Profile page shows the empty state, Jobs page shows the banner, and their profile is independent of the first user's.
- `psql`: `select id, user_id from profiles order by id;` — a second upload by the same user adds a **new row** (append-only), and the page shows the newest.
- This is the first authenticated call from a real browser → tick BUILD_PLAN Slice 6.5's "Real end-to-end verification" item.

---

## Step 4 — Job Detail + Score Fit panel

**Why:** the app's first agent-backed UI. Teaches: dynamic route params (strings → numbers), avoiding conditional hooks by splitting a component, a 4-state async panel (idle / loading / result / error), populating a query cache from a mutation, treating a multi-second agent call as a UI state (no streaming exists — Mangum buffers).

**Build:**
1. `hooks/useJobs.js` — add `useJob(jobId)`: `queryKey: queryKeys.job(jobId)`, `queryFn: () => api(`/jobs/${jobId}`)`, `staleTime: 5 * 60_000`.
2. `hooks/useScoreFit.js`:
   - `useScoreFit(jobId, { enabled = true } = {})`: `queryKey: queryKeys.score(jobId)`; `queryFn` = `GET /jobs/${jobId}/score`, returning `null` on `ApiError` 404 (same pattern as `useProfile`); `staleTime: Infinity` (it only changes via the mutation below or a profile upload's invalidation); pass `enabled` through to `useQuery`. `JobDetail` (below) calls this with `enabled: isSignedIn` — signed out, this must never fire (it would just 401).
   - `useRunScoreFit(jobId)`: `useMutation` with `mutationFn: () => api(`/jobs/${jobId}/score`, { method: 'POST' })` (no body); hook-level `onSuccess(result)`: `queryClient.setQueryData(queryKeys.score(jobId), result)` — the GET cache now holds the fresh result and the chat unlocks with no extra request.
3. `lib/match.js` — export `MATCH_META` keyed by the five `match` values, each `{ label, description, className }` (descriptions copied verbatim from `MATCH_DEFINITIONS` in `src/jobsentinel/agent/shared/schema.py`), used as `Badge` `className`:
   - `strong_match` — "Strong match" — `bg-emerald-600 text-white`
   - `good_match` — "Good match" — `bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200`
   - `potential_match` — "Potential match" — `bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200`
   - `weak_match` — "Weak match" — `bg-orange-100 text-orange-900 dark:bg-orange-900/40 dark:text-orange-200`
   - `not_a_match` — "Not a match" — `bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-200`

   Also export `GAP_TYPE_LABELS`: `not_mentioned` → "Not in your profile", `contradicts` → "Conflicts with your profile", `posting_underspecified` → "Posting is unclear".
4. `components/jobs/FitAssessmentView.jsx` — prop `assessment`. Top row: large `Badge` (`MATCH_META[match].className`, `px-3 py-1 text-sm`) + the muted description beneath it. Then `summary` paragraph. **Strengths** (`h3`): each item → `CheckCircle2` icon (`text-emerald-600`) + `requirement` (`font-medium`) + `evidence` (`text-sm text-muted-foreground`). **Gaps** (`h3`): each → `AlertCircle` icon (`text-amber-600`) + `requirement` + `Badge variant="outline"` with `GAP_TYPE_LABELS[gap_type]` + `note` when non-null. Empty list → muted "None identified." Finally the `recommendation_note` in `<div className="rounded-lg bg-muted p-3 text-sm">` under a "Recommendation" label.
5. `components/jobs/ScoreFitPanel.jsx` — prop `jobId`. Calls `useProfile()`, `useScoreFit(jobId)` and `useRunScoreFit(jobId)`. Render by this precedence:

   | Condition | Render |
   |---|---|
   | profile or score `isPending` | 3 `Skeleton` lines |
   | profile or score `isError` | `ErrorAlert` (retry = that query's `refetch`) |
   | `profile === null` | "Upload your resume first to score this job." + `Link to="/profile"` styled `buttonVariants()` |
   | `score === null`, not running | "Not scored yet against your current resume." + `Button` "Score fit" → `run.mutate()` |
   | `score === null`, `run.isPending` | Button disabled with spinning `Loader2` + "Analyzing fit… this can take up to a minute" |
   | `score` exists | `<FitAssessmentView />` + `Button variant="outline" size="sm"` "Re-run" with `RefreshCw` (disabled + spinning icon and "Re-scoring…" while `run.isPending`; the old result stays visible meanwhile) |
   | `run.isError` (any state above) | `<ErrorAlert error={run.error} title="Scoring failed" onRetry={() => run.mutate()} />` |
6. `pages/JobDetailPage.jsx`:
   - **Split into two components in the same file** to keep hooks unconditional: default-exported `JobDetailPage` reads `useParams().jobId`, computes `const jobId = Number(raw)`, and returns `<NotFoundPage />` when `!Number.isInteger(jobId)`; otherwise renders an inner `JobDetail({ jobId })` that owns all the hooks. (Early-returning above hooks in one component would violate the Rules of Hooks.)
   - In `JobDetail`: `const job = useJob(jobId)`. `job.isPending` → skeletons; `job.isError` and `job.error.status === 404` → "Job not found" + link back; other errors → `ErrorAlert`.
   - Header: back `Link to="/jobs"` (`ArrowLeft` + "All jobs", `buttonVariants({ variant: 'ghost', size: 'sm' })`); `h1` = title; a row with `Badge variant="secondary"` (`board_token`), muted `Fetched {formatDate}`, and — only if `job.url` — `<a href={job.url} target="_blank" rel="noreferrer">` "Original posting" + `ExternalLink` icon.
   - **Auth gate for the right panel (Decision 9/10):** `const { isSignedIn } = useAuth()` (`@clerk/clerk-react`) and `const score = useScoreFit(jobId, { enabled: isSignedIn })` — declared here, once, at the top of `JobDetail`; Step 5 reuses this same `score` (don't re-declare it in a child).
   - Body: `<div className="grid gap-6 lg:grid-cols-2 lg:items-start">`. **Left:** `Card` "Posting" whose content is `<div className="whitespace-pre-wrap break-words text-sm leading-relaxed">{job.description}</div>` (the description is plain text; `whitespace-pre-wrap` preserves its line breaks — do **not** use `dangerouslySetInnerHTML`). This side always renders, signed in or not.
   - **Right, signed out** (`!isSignedIn`): render a `Card` in place of the Tabs — `CardTitle` "Sign in to see your fit", `CardDescription` "Score this job against your resume and get help tailoring it — sign in first." — with a `flex gap-2` button row: `Link to="/sign-in"` (`buttonVariants({ size: 'sm' })`) "Sign in" and `Link to="/sign-up"` (`buttonVariants({ variant: 'outline', size: 'sm' })`) "Sign up". `ScoreFitPanel`/the chat are never mounted in this branch — no authenticated request is attempted.
   - **Right, signed in:** shadcn `Tabs` with `value={tab}` / `onValueChange={setTab}` from `const [tab, setTab] = useState('fit')`; `TabsList` with triggers "Fit score" (`value="fit"`) and "Job Agent" (`value="agent"`, `disabled` for now); `TabsContent value="fit"` → `<ScoreFitPanel jobId={jobId} />`. Step 5 enables and fills the second tab. No sticky positioning, no auto-switching tabs after scoring.

**Done when:**
- `/jobs/182`: posting text keeps paragraph/bullet line breaks; "Score fit" → loading state → assessment renders (badge color, strengths, gaps with type badges, recommendation). Network tab shows one `POST /jobs/182/score`.
- Hard-refresh → result appears from a single `GET /jobs/182/score` (no POST, no new `agent_runs` row).
- "Re-run" replaces the result and creates a new `agent_runs` row (`select id, kind, outcome from agent_runs order by id desc limit 3;`).
- Second user with no resume sees the "upload your resume first" state on the same job. `/jobs/999999` and `/jobs/abc` both show a not-found state (not a crash, not endless skeletons).
- **Sign out and open `/jobs/182` directly:** the posting still renders (public); the right panel shows the "Sign in to see your fit" card instead of Tabs, and no `GET /jobs/182/score` request fires (Network tab — proves `enabled: isSignedIn` worked, not just that the UI hid the result).
- Upload a new resume, return to the job → "Not scored yet" (proves the invalidation from Step 3); the Job Agent tab is still disabled.

---

## Step 5 — Job Agent chat (the core UI)

**Why:** the point of the app. Teaches: chat state design with server-state + mutation-state (no manual `messages` array), showing an in-flight message from `mutation.variables`, cache updates with an updater function, gating UI on derived server state, auto-scroll with a ref + effect, Markdown rendering safely (no raw HTML), deriving state instead of syncing it with effects.

**Build:**
1. `hooks/useJobAgent.js`:
   - `useJobAgentHistory(jobId, { enabled })`: `queryKey: queryKeys.agent(jobId)`, `queryFn: () => api(`/jobs/${jobId}/agent`)`, `enabled`, `staleTime: Infinity`, `refetchOnWindowFocus: false` (Decision 6).
   - `useSendJobAgentMessage(jobId)`: `mutationFn: (message) => api(`/jobs/${jobId}/agent`, { method: 'POST', body: { message } })`; hook-level `onSuccess(data, message)` → `queryClient.setQueryData(queryKeys.agent(jobId), (old) => old === undefined ? undefined : [...old, { role: 'user', text: message }, { role: 'assistant', text: data.reply }])`. Returning `undefined` when nothing is cached leaves the cache empty so the next mount fetches the true history instead of showing a partial one.
2. `components/jobs/ChatMessage.jsx` — props `role`, `text`. `role === 'user'`: right-aligned bubble — `ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-3 py-2 text-sm text-primary-foreground`. Any other role: left bubble — `max-w-[90%] rounded-2xl bg-muted px-3 py-2` containing `<div className="prose prose-sm max-w-none dark:prose-invert"><ReactMarkdown>{text}</ReactMarkdown></div>` and beneath it a `Button variant="ghost" size="icon-xs"` (`aria-label="Copy message"`) that calls `navigator.clipboard.writeText(text)`, swaps `Copy` → `Check` for 1.5 s via a local `copied` `useState` + `setTimeout`. Do **not** add `rehype-raw` (react-markdown escapes HTML by default, which is what you want for model output).
3. `components/jobs/JobAgentChat.jsx` — prop `jobId`. Hooks: `useJobAgentHistory(jobId, { enabled: true })`, `useSendJobAgentMessage(jobId)`, `const [draft, setDraft] = useState('')`, a `bottomRef`.
   - **Container:** `<div className="flex h-[70vh] min-h-[420px] flex-col rounded-xl border">`. **Message list:** `flex-1 space-y-3 overflow-y-auto p-4` with `role="log"` and `aria-live="polite"`. **Composer:** `flex items-end gap-2 border-t p-3` with shadcn `Textarea` (`rows={2}`, `className="min-h-0 resize-none"`, `aria-label="Message the Job Agent"`, `placeholder="Ask about this job, or say 'help me tailor my resume'…"`) and `Button size="icon"` (`SendHorizontal`, `aria-label="Send"`, disabled when the draft is blank, when `send.isPending`, or when history isn't loaded).
   - **Render states** for the message list: history `isPending` → 3 skeleton bubbles; history `isError` → `ErrorAlert` with retry; empty history and not sending → short intro ("Ask about the gaps, or have me tailor your resume or draft a cover letter for this role.") plus three `Button variant="outline" size="sm"` starters that call `send(text)` directly: "Which gaps matter most for this role?", "Help me tailor my resume for this job", "Draft a cover letter for this job"; otherwise map history → `ChatMessage` (`key={index}`).
   - **In flight** (`send.isPending`): after the history, render a user `ChatMessage` from `send.variables`, then an assistant-style bubble with spinning `Loader2` + "Thinking…".
   - **`send(text)`:** trim; return if empty or `send.isPending`; `setDraft('')`; `send.mutate(text, { onError: () => setDraft(text) })` (call-level `onError` is fine here — restoring the draft only matters while the component is mounted). Show `<ErrorAlert error={send.error} title="Message failed" />` just above the composer.
   - **Keyboard:** `onKeyDown` on the textarea — `Enter` without `Shift` and not `e.nativeEvent.isComposing` → `preventDefault()` and `send(draft)`; `Shift+Enter` inserts a newline (default behavior).
   - **Auto-scroll:** an empty `<div ref={bottomRef} />` at the end of the list; `useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), [history.data?.length, send.isPending])`.
4. **Wire into `JobDetailPage`'s `JobDetail`:**
   - `score` is already declared at the top of `JobDetail` from Step 4 (`useScoreFit(jobId, { enabled: isSignedIn })`) — reuse it, don't call the hook again here. `const canChat = isSignedIn && score.data != null;` (`isSignedIn` is redundant with the fact that this whole Tabs branch only renders when signed in, but keeps `canChat` correct if that ever changes). Reusing the same query key as `ScoreFitPanel`'s own internal call means React Query dedupes them — no second request.
   - **Derive, don't sync:** `const activeTab = canChat ? tab : 'fit';` and pass `activeTab` as the Tabs `value` (so if a profile upload invalidates the score while you're on the chat tab, the UI falls back to "Fit score" without a `useEffect`).
   - Job Agent trigger: `disabled={!canChat}`; add a `title`/muted hint "Score this job first" when disabled. `TabsContent value="agent"` renders `{canChat && <JobAgentChat jobId={jobId} />}`. (Switching tabs unmounts the chat and loses an unsent draft; accepted — history and any in-flight mutation live in the query cache/mutation cache and survive.)

**Done when:**
- On a scored job (182) the Job Agent tab is enabled; on an unscored job it's disabled with the hint.
- Empty state shows the three starters; click "Help me tailor my resume…" → your bubble + "Thinking…" → Markdown-rendered reply appears. Send a follow-up ("what did you mean by …") — it remembers context.
- Enter sends, Shift+Enter adds a newline; list auto-scrolls; the copy button copies the reply text.
- Hard-refresh mid-conversation → full history reloads in order from `GET /jobs/182/agent`. Network tab: no `GET …/agent` fires after a send (Decision 6). Verify the `role` strings in that response are `user`/`assistant`.
- A different job has its own empty conversation.
- Stop uvicorn, send a message → `ErrorAlert` "Message failed" and your text returns to the textarea.
- Upload a new resume while on the chat tab → tab falls back to "Fit score" and the chat is disabled until re-scored.

---

## Step 6 — Hardening, full walkthrough, doc sync

**Why:** BUILD_PLAN's last Slice 7 item is a real-browser walkthrough; this is also where you check the states you didn't hit on the happy path. Teaches: reading your own UI as a user, responsive checks, keeping the plan honest.

**Build / check:**
1. **State audit** — for each of the 3 pages + `ScoreFitPanel` + `JobAgentChat`, confirm each has a loading, error (with retry where a query exists), and empty state you've actually seen render (throttle the network in DevTools to see skeletons; stop uvicorn to see errors).
2. **Responsive** — DevTools at 375 px width: jobs table hides Source/Fetched columns without horizontal scroll, Job Detail stacks (posting, then tabs), chat composer stays usable, header doesn't overflow.
3. **Keyboard/a11y quick pass** — tab through the job filter, table links, tabs, textarea, send button; every interactive element has a visible focus ring and an accessible name (icon-only buttons have `aria-label`).
4. `npm run lint`, `npm run build`, then `npm run preview` and load the built app once.
5. **Full walkthrough** (fresh browser/incognito, signed out throughout the first stage, one hard-refresh after each later stage): land on `/` → hero renders, no redirect → "Browse jobs" → `/jobs` loads and filters signed out → open job 182 → posting renders, right panel shows "Sign in to see your fit" → "Sign in" → sign up a new `+clerk_test` user → redirected back → Jobs banner ("sign in to score jobs" banner is gone now that you're signed in; "upload your resume" banner shows instead) → upload resume → profile renders → back to job 182 → Score fit → open Job Agent → 3 turns (gap question, resume help, cover letter) → refresh → sign out (from `UserButton`, while sitting on `/jobs/182`: confirm you're **not** redirected — the posting stays visible, the right panel reverts to the sign-in card) → sign in again → everything still there. Then a second `+clerk_test` user in incognito: confirm they see none of the first user's profile, scores, or chat.
6. **Docs (per CLAUDE.md "don't silently drift"):** tick the Slice 7 checkboxes and Slice 6.5's "Real end-to-end verification" in `BUILD_PLAN.md`; in `CLAUDE.md` update "Project status" (frontend now exists; add `cd frontend && npm run dev` and the `frontend/.env.local` requirement to the daily commands); add any deviations you actually made to BUILD_PLAN's Slice 7 section.

**Done when:** the walkthrough passes end to end with no console errors and no unhandled promise rejections in DevTools.

---

## Appendix A — Concepts checklist (what this slice should leave you able to explain)

- Why CORS preflight exists and what `allow_headers` is for; why Bearer tokens don't need `allow_credentials`.
- Why `FormData` bodies must not get a manual `Content-Type`.
- Server state vs. client state, and why almost nothing here is in `useState`.
- Query keys as a cache address; prefix invalidation (`['score']`) vs. exact keys (`['score', 182]`).
- `setQueryData` (write what you already know) vs. `invalidateQueries` (mark stale and refetch), and when each is correct — Steps 3–5 use both.
- Hook-level vs. call-level mutation callbacks and what happens on unmount.
- `isPending` / `isError` / `data === null` as three distinct states.
- Rules of Hooks and why `JobDetailPage` is split in two.
- Deriving state (`activeTab`) instead of syncing it with an effect.
- Why the API can't stream (Mangum buffers) and how a progress state substitutes.

## Appendix B — Deferred (not this slice, on purpose)

Pagination / server-side filtering; score badges on the job list (needs a bulk score endpoint); choosing among historical profiles (`?id` / `profile_id`); long-term-memory UI; streaming; dark-mode toggle; toasts; automated frontend tests (Vitest + Testing Library is the natural next addition); production hosting (S3 + CloudFront) and the Function URL's CORS config.
