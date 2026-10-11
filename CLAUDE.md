# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Tomo** (formerly "AI Planner"): a local-first, single-user scheduler. Users manage goals, tasks, recurring routines and fixed obligations; a CP-SAT solver (OR-Tools) places work into 15-minute slots over a 1–14 day horizon; a chat assistant (Gemini, or a deterministic demo parser) turns natural language into typed actions that are previewed as a **proposal** (apply / discard / undo) before anything is saved. An optional native Windows companion reports coarse foreground-app/idle activity, which can produce replanning *suggestions* that the user must confirm.

It is a modular monolith with three deployables:

| Directory | Stack | Role |
| --- | --- | --- |
| `backend/` | Python 3.11+ (3.12 in CI), FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, OR-Tools, google-genai | Owns all state and business logic |
| `frontend/` | Next.js 16 (App Router), React 19, TypeScript (strict), plain CSS tokens, `next/font` | Renders REST resources; no business logic |
| `desktop-agent/` | C++17, CMake, Win32 + WinHTTP (no third-party libs) | Opt-in activity sampler, Windows only |

Deeper docs live in `docs/` — `ARCHITECTURE.md`, `SCHEDULER.md` (solver constraints/objective), `API.md`, `DESKTOP_AGENT.md`, `DEVELOPMENT.md`, `IMPLEMENTATION_STATUS.md`. Read `SCHEDULER.md` before touching `scheduler.py`.

## Architecture

### Request flow

```
Next.js page ─► components/planner.tsx ─► lib/api.ts fetch("/api/...")
   └─ next.config.ts rewrite /api/* ─► FastAPI (API_BASE_URL, default http://127.0.0.1:8000)
        └─ app/main.py route ─► app/services/* ─► SQLAlchemy models ─► PostgreSQL (or SQLite)
```

The browser never talks to FastAPI directly; Next.js rewrites `/api/*` to the backend. Gemini keys exist only on the backend.

### Backend layout (`backend/app/`)

- `main.py` — every HTTP route, CORS, and global exception handlers (Pydantic `ValidationError` → 422, `OperationalError` → 503). Routes are thin: lock preferences, call a service, return ORM rows serialized via `response_model`. Mutations of tasks, obligations and preferences call `upkeep.replan()` in the same transaction; `GET /api/overview` and `GET /api/sessions` call `upkeep.settle()` and `upkeep.ensure_plan()` first.
- `config.py` — `Settings` (pydantic-settings) reads `../.env` then `.env`. Access via cached `get_settings()`.
- `db.py` — engine/session factory, `get_db` dependency (commits on success, rolls back on exception), `UTCDateTime` type decorator, `utcnow()`.
- `models.py` — ORM tables: `Goal`, `Task` (with `category`: focus/routine/personal/errand), `Obligation` (with `kind`: commitment/appointment/interview/personal; one-off events use equal `start_date`/`end_date`), `Preference` (singleton, `id = 1`; `planned_through` tracks the planned horizon), `ScheduleSession`, `ActivityEvent`, `Suggestion`, `ChatMessage` (optional `proposal_id`), `Proposal`. Invariants are enforced with DB `CheckConstraint`s as well as schemas.
- `schemas.py` — Pydantic I/O models. All inherit `Schema` (`from_attributes=True`, `extra="forbid"`, `str_strip_whitespace=True`). Shared constrained types: `Title`, `Minutes` (multiple of 15), `Clock` (`HH:MM`).
- `services/resources.py` — CRUD helpers: `require()` (404), `preferences(db, lock=...)`, create/update task, obligation, session, `invalidate_future()`.
- `services/scheduler.py` — `generate_plan()`: builds work units, computes legal start domains, solves CP-SAT, replaces only movable sessions.
- `services/ai/actions.py` — discriminated union of typed actions (`kind` field): `create_goal`, `create_task`, `update_task`, `create_obligation`, `set_preference`, `reschedule`, `complete_task`, `clarify`, wrapped in `ActionBatch`.
- `services/ai/interpreter.py` — `interpret()` dispatches to `demo_interpret()` (regex/keyword parser over `DEMO_COMMANDS`) or Gemini with structured output (`provider_schema()` converts the Pydantic schema to Gemini's `anyOf` form), then re-validates strictly with `ActionBatch.model_validate_json`.
- `services/ai/pipeline.py` — `propose()`: interpret **before** taking the DB lock, dry-run the batch with `apply_batch()` + replan, `describe()` the session diff, then `db.rollback()` and store a `Proposal`. `apply_proposal()` snapshots state, then restores the stored previewed result (`Proposal.result`) if the state still matches `Proposal.base_fingerprint`, so Apply is instant and matches the preview; otherwise it re-runs the stored batch and plans again; `undo_proposal()` restores the snapshot only if the state fingerprint is unchanged; `discard_proposal()`; `current_proposal()`.
- `services/upkeep.py` — work the UI never asks for: `settle()` credits elapsed planned sessions as completed (with a 30-min grace and skipping sessions with pending suggestions when monitoring is on), `replan()` (7 days), `ensure_plan()` (rolls the horizon forward and swallows 409s), `session_views()` (sessions plus category/goal subtitle/deadline for the calendar).
- `services/history.py` — whole-table `snapshot()` / `restore()` / `fingerprint()` of goals, obligations, tasks, sessions, suggestions and preferences, used by undo.
- `services/feeds.py` — connected calendar feeds (`CalendarSource`, `ExternalEvent`): `pull()` fetches and parses an .ics feed with no DB lock held (`_settled()` commits the read transaction first), `store()` upserts by feed UID so row ids stay stable, `connect()`/`sync()`/`sync_stale()`/`disconnect()` replan afterwards. Imported timed events join the solver's fixed intervals after the fixed-overlap check (they may overlap anything); deadlines and all-day items feed the overview's DUE strip and Coming up. `demo_feed()` generates the demo Canvas calendar (`demo://canvas`). Feed URLs are secrets; only `url_hint()` leaves the backend.
- `services/demo.py` — demo-only `clear()` / `populate()` behind `/api/demo/*` (403 unless demo mode or a demo clock); `seed.add_sample_data()` is shared with the `python -m app.seed` command. The chat shows them as "Load sample data" / "Clear the calendar" tool chips (clear needs a second click).
- `services/overview.py` — `build()` for `GET /api/overview`: Coming up items, goal progress, day/week stats, headline, briefs, DUE deadlines, chat prompt chips and the visible hour range.
- `services/activity.py` — ingest agent events (idempotent by event UUID), evaluate suggestions, confirm/dismiss.
- `seed.py` — sample data (`python -m app.seed`).

### Core invariants (do not break)

- **Concurrency:** every mutating path calls `resources.preferences(db, lock=True)` first. On PostgreSQL this is `SELECT ... FOR UPDATE` on the singleton row and serializes all schedule mutations. New mutating endpoints must do the same.
- **Atomicity:** an action batch plus schedule replacement commits together or rolls back. Proposals are computed in a transaction that is rolled back; only `apply` commits the batch. Raise `HTTPException` to abort; don't commit mid-request (`get_db` commits). Use `db.flush()` when you need IDs.
- **Time:** all timestamps are timezone-aware UTC across every boundary. `UTCDateTime` rejects naive datetimes. API inputs use `AwareDatetime`. The user's IANA timezone (`Preference.timezone`) defines local days, sleep and availability windows; handle DST through `zoneinfo`.
- **Scheduling:** 15-minute slots, max 14 days and 100 work units, 8s solve limit, one worker, fixed seed. Completed, locked and in-progress sessions and fixed obligations are never moved by the solver. Conflicts return 409 and keep the existing schedule. Never fabricate a schedule on INFEASIBLE/UNKNOWN.
- **AI safety:** the LLM only proposes actions; the backend validates and applies them. Never let it invent IDs or schedule times directly. User/stored text is treated as untrusted data. Provider errors map to 502/503 without leaking prompts or keys. The assistant must not toggle `monitoring_enabled`; that change happens only in Settings.
- **Automatic upkeep:** the UI has no "generate plan" or "mark done" controls. Keep it that way: any new mutation that affects scheduling must replan in its own transaction, and reads settle and extend the plan. `generate_plan()` validates and solves before its first write; `ensure_plan()` relies on that to fail without partial changes (no savepoints, which pysqlite handles poorly).
- **Activity:** requires the backend Settings opt-in, `AGENT_TOKEN` (checked with `secrets.compare_digest`), and the agent's `--enable` flag. Suggestions never mutate the plan until the user confirms them, and activity never marks work complete.

### Frontend layout (`frontend/`)

The UI implements the "Tomo" Day and Week design mockups. `app/globals.css` holds their exact values as CSS variables (`--bg #F4F5F1`, `--ink #15201B`, `--accent #D9531E`, and so on) and classes; category and kind colors live in `lib/calendar.ts`. Match those values instead of inventing new ones. **Dark mode:** every color is a token on `:root`, with dark values under `:root[data-theme="dark"]` and a `prefers-color-scheme: dark` block (system default). Never hard-code a color in CSS or inline styles: use `var(--…)` (category and kind colors are `--focus`, `--fixed-bg`, etc., referenced from `lib/calendar.ts`). The header `ThemeToggle` stores an explicit choice in localStorage (`lib/theme.ts`), and `THEME_SCRIPT` in `app/layout.tsx` applies it before first paint; it must live in a non-client module, since a value imported from a `"use client"` file into a server component becomes a client reference.

- `app/(planner)/layout.tsx` renders `<Suspense><Planner /></Suspense>` once; `app/(planner)/page.tsx`, `week/page.tsx` and `month/page.tsx` return `null`. Because the planner lives in the shared layout it stays mounted when switching views — don't move it back into the pages. The view comes from `usePathname()`; the visible date is the `?date=YYYY-MM-DD` query param (absent means today in the user's timezone).
- `components/planner.tsx` — client shell: header (prev/today/next, Day/Week/Month tabs, settings), chat actions, the global `/` shortcut, and dialogs. Range data (`/overview` then `/sessions`) is cached per `view:start` key: the visible range refreshes first while cached data stays on screen, then the other two views for the date are prefetched. Chat data (`/messages`, `/proposals/current`, `/suggestions`) is loaded separately. After any change, `refresh()` drops the cache and bumps `generation`.
- `components/schedule.tsx` — `DayView`, `WeekView` (DUE row) and `MonthView` (6×7 grid). `useAvailableHeight()` measures the window space below the grid (on layouts wider than 1100px): Day/Week stretch hours to fill it, but booked hours never drop below a readable minimum (64px Day, 50px Week). Beyond that the calendar extends down and the page scrolls; the week's day headers stick to the top of the window and the sidebar and chat stay pinned (`position: sticky`). Phones will get a separate app, so the narrow layout is not a priority.
- Calendar "shows": every change to the sessions of the range on screen (chat preview, Apply/Discard/Undo, dialog saves, background refreshes) is staged by `useStage()` in `planner.tsx`. It gives each session a stable visual key with `matchKeys()` (same id, then same task at the same time, then same task nearest in time; the solver recreates moved rows with new ids) and keeps what was on screen as `before`, chained from whatever is displayed even mid-show. The views pass both layouts to `choreograph()`, which pairs blocks by key: removed blocks are struck through then fade, blocks displaced by the hour scale shift with the hour lines, moved blocks travel one by one, then new boxes are drawn and typed in. Navigating to a different range swaps instantly; `prefers-reduced-motion` skips shows. Rules that keep anything from teleporting: one element per key for its whole life (never re-key on screen), and blocks render in a fixed key order (React reordering children moves DOM nodes, which cancels their transitions). Week blocks share one `.week-blocks` layer so they can cross days. Timings are in `TIMING`, keyframes in `globals.css`.
- `components/sidebar.tsx` — Coming up (filter pills) and Goals.
- `components/assistant.tsx` — collapsible "Plan with Tomo" panel: brief, message history, `ProposalCard` (Apply/Discard), activity check-in cards, Undo on the "Done." reply, prompt chips.
- `components/dialogs.tsx` — `EventDialog` (add/edit/delete fixed events), `GoalDialog` (goal plus steps), `SettingsDialog` (preferences and the monitoring opt-in).
- `lib/calendar.ts` — pure, unit-tested helpers: `busyHours()` / `fitUnit()` / `hourScale()` / `yAt()` build the adaptive time scale (hours with nothing booked shrink to `EMPTY_HOUR` of a booked hour; Week uses one scale for all seven days so columns align), `layout()` positions blocks on a `Scale` and derives Done/Due/Proposed tags, `withPreview()` overlays a pending proposal, plus `rangeFor()`, `shift()`, `weekStart()` and `isoWeek()`.
- `lib/api.ts` — `api<T>(path, method, body)` fetch wrapper. It prefixes `/api`, sets a 45s timeout, and turns FastAPI `detail` (string or validation list) into an `Error`.
- `lib/types.ts` — hand-written TS interfaces that mirror backend schemas. **Update them whenever `schemas.py` changes.**
- `lib/time.ts` — timezone-aware date helpers (`zonedISO`, `dateKey`, `addDays`, etc.).

### Desktop agent (`desktop-agent/`)

`src/main.cpp` (CLI: `--enable`, `--backend`, `--once`, `--probe`, `--test-report`, `--self-test`), `src/activity.cpp` (foreground process basename + idle via `GetLastInputInfo`), `src/http.cpp` (WinHTTP, loopback-only, no redirects). It sends executable basenames only — no window titles, paths, keystrokes or screenshots. Keep it that way.

## Coding conventions

### Python
- Ruff: line length 100, rules `E4, E7, E9, F, I` (import sorting enforced). Format with `ruff format`.
- Absolute imports from `app.` (`from app.services import resources`).
- Modern typing: `X | None`, `Annotated[...]`, SQLAlchemy 2 `Mapped[...]`/`mapped_column`.
- Functions over classes for services. Services take `db: Session` first and accept an optional `now` parameter for deterministic tests.
- Errors: raise `fastapi.HTTPException` with user-readable messages that say what to do (for example "Run alembic upgrade head."). Status codes: 404 missing, 409 conflict/infeasible, 422 invalid, 502 bad provider output, 503 unavailable/not configured.
- Validation lives in Pydantic schemas (`field_validator` / `model_validator(mode="after")`) and is mirrored by DB check constraints.
- Comments are sparse and explain *why* (for example "Interpret before acquiring the write lock; network latency must not hold DB locks.").

### TypeScript / React
- Strict TS. Compact style: short components, often single-line JSX and interfaces, semicolons, double quotes.
- Data access only through `api()` from `lib/api.ts`; don't call `fetch` directly or hardcode the backend URL.
- Styling uses classes and tokens in `app/globals.css` (no Tailwind, no icon library; the few icons are inline SVG from the mockups). Use inline `style` only for per-item computed values (positions, category colors).
- React Compiler lint rules are on: don't `setState` synchronously in effects, and avoid manual `useCallback`/`useMemo` that the compiler can't preserve. Load data in effects with a `live` flag (see `planner.tsx`).
- Relative imports (`../lib/api`) are used even though the `@/*` alias exists; follow the existing style.
- File names are kebab-case; the main component of a file is its default export.

### C++
- C++17, `UNICODE`, `WIN32_LEAN_AND_MEAN`, `NOMINMAX`; `/W4 /permissive-` (MSVC) or `-Wall -Wextra -Wpedantic`. Headers in `include/`, sources in `src/`.

### Database changes
1. Edit `app/models.py` (and matching `schemas.py` / `frontend/lib/types.ts`).
2. Generate a migration: `alembic revision --autogenerate -m "..."` from `backend/`, then review it. **On SQLite, avoid batch rebuilds of existing tables**: they silently drop the unnamed CHECK constraints from the initial migration. Use `ALTER TABLE ... ADD COLUMN` with inline constraints instead (see `b7d41c2e9a10_tomo_planner.py`).
3. `alembic upgrade head`, then `alembic check` must report no drift on PostgreSQL (CI enforces this). On SQLite, `alembic check` falsely reports the inline `chat_messages.proposal_id` FK, because SQLAlchemy doesn't reflect its `ON DELETE`.

## Development workflow

Commands assume PowerShell from the repo root (the project is Windows-first; on macOS/Linux use `.venv/bin/python`).

### Run
```powershell
Copy-Item .env.example .env            # backend config: DATABASE_URL, AI_MODE, GEMINI_*, AGENT_TOKEN, CORS_ORIGINS
docker compose up --build -d           # postgres:17 + backend on 127.0.0.1:8000 (runs migrations on start)
docker compose exec backend python -m app.seed   # optional sample data
cd frontend; npm ci; npm run dev       # http://127.0.0.1:3000
```
Without Docker, see `docs/DEVELOPMENT.md`. For example, a standalone SQLite demo uses `$env:DATABASE_URL="sqlite:///daylight.db"`, then runs `alembic upgrade head`, `python -m app.seed`, and `uvicorn app.main:app`. `AI_MODE=demo` (default) needs no API key. API docs: http://127.0.0.1:8000/docs.

Backend venv setup:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e backend
.\.venv\Scripts\python.exe -m pip install pytest ruff
```
Dependencies are pinned in `backend/requirements.lock` and `frontend/package-lock.json`. Update the lock files when you add a dependency.

### Test and lint (run what CI runs before considering work done)
```powershell
# Backend (from repo root)
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m ruff format --check backend

# Frontend (from frontend/)
npm run typecheck; npm run lint; npm test; npm run build

# E2E (needs running API + frontend on an ISOLATED demo DB — it creates data)
npm run test:e2e

# Desktop agent
cmake -S desktop-agent -B desktop-agent/build -A x64
cmake --build desktop-agent/build --config Release
ctest --test-dir desktop-agent/build -C Release --output-on-failure
```

### Testing patterns
- `backend/tests/conftest.py` sets `DATABASE_URL=sqlite://`, `AI_MODE=demo` and `AGENT_TOKEN` **before** importing the app. The `db` fixture creates a fresh SQLite file per test with the `Preference(id=1)` row. The `client` fixture overrides `get_db` with a `TestClient`.
- Scheduler tests pin a fixed `NOW` (for example a Monday 07:00 Los Angeles time expressed in UTC) and call `generate_plan(db, PlanRequest(...), now)` directly. Pass `now` explicitly instead of relying on wall-clock time.
- Gemini is never called live in tests; mock the SDK.
- Proposal flow tests post to `/api/assistant` and then `/api/proposals/{id}/apply` (see `propose_and_apply` in `test_ai.py`). Upkeep and overview tests are in `test_upkeep.py`.
- Frontend unit tests use Vitest + jsdom + Testing Library (`frontend/tests/*.test.ts(x)`). Playwright workflows are in `frontend/e2e/` and expect the seed data (for example "Dentist cleaning" and "Build confidence in C++"). Set `CHROME_PATH` to use an installed Chrome.
- `node frontend/scripts/capture.mjs` (with both servers running; optional `CAPTURE_DATE`) regenerates `docs/screenshots/*.png`.

### CI (`.github/workflows/ci.yml`)
Four jobs: **backend** (ruff, `alembic upgrade head && alembic check` on Postgres 17, pytest, seed, `scripts/postgres_smoke.py`), **frontend** (typecheck, lint, vitest, build, `npm audit --omit=dev --audit-level=high`), **windows-agent** (MSVC build, CTest, `agent_smoke.py`), **browser-workflows** (SQLite demo backend + `next start` + Playwright).

## Gotchas

- Docker binds ports to `127.0.0.1` only; the backend is not meant to be exposed.
- `npm run dev` binds to `127.0.0.1`; the first page compile takes about 30 seconds. `npm run lan` builds and serves on `0.0.0.0` for other devices on the network; keep the backend on `127.0.0.1` (the Next.js server proxies `/api`). There is no auth, so LAN mode is opt-in. Turbopack sometimes keeps serving a stale server compile after a component's props change (symptom: server render errors that don't match the source); restart the dev server.
- The fit-to-window sizing uses `ResizeObserver` and `requestAnimationFrame`, which don't fire in a browser tab that isn't rendering (for example a hidden preview pane), so measure layout there only after forcing a render.
- Playwright tests assume freshly seeded data; rerunning them against the same database fails. Recreate the e2e database first.
- Running the dev server rewrites `frontend/next-env.d.ts` to point at `.next/dev/types`; don't commit that change.
- Elapsed sessions become `completed` on the next read, so tests that need a session to stay `planned` must call services directly, not go through `GET /api/sessions` or `/api/overview`.
- `CORS_ORIGINS` must include the frontend origin if you change ports.
- `.vscode/settings.json` hardcodes `cmake.sourceDirectory` to `E:/Projects/AISchedule/desktop-agent`, which is the original author's machine. Adjust it locally if CMake Tools complains.
- `scripts/stop-preview.ps1` stops a portable preview recorded under the ignored `artifacts/` directory. It doesn't apply to the Docker setup.
- Never commit `.env`, `*.db`, API keys or agent tokens (`.gitignore` covers them).
- Known limits (single availability window per day, obligations within one day, weekly recurrence as a time budget) are listed in `docs/IMPLEMENTATION_STATUS.md`. Check there before "fixing" something that is a deliberate limit.
