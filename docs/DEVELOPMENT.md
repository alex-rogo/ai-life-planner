# Development

Additional setup, configuration, and validation commands. For the default setup, see the [README](../README.md).

## Run FastAPI directly

Requirements: Python 3.11+ (3.12 tested). Start just PostgreSQL with `docker compose up -d db`, or supply a local PostgreSQL URL.

```powershell
# Repository root
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e backend

cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.seed
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

On macOS/Linux use `.venv/bin/python` instead of `.venv\Scripts\python.exe`. The Windows companion requires Windows.

### Standalone demo without Docker

Change the backend database URL for that terminal only; this uses a persistent SQLite file:

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///daylight.db"
$env:AI_MODE = "demo"
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.seed
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the frontend as above. PostgreSQL remains the intended runtime database and is separately exercised by the CI migration/persistence job.

## Gemini configuration

Set backend-only values in the root `.env`:

```dotenv
AI_MODE=gemini
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash
```

Choose a structured-output-capable model available to your Google account. Restart FastAPI (or recreate the Compose backend) after changing environment variables. A missing key, provider failure or malformed response returns a clear error without applying changes. Keys are never returned by the API, passed to the web application or committed.

The integration uses the [Google structured output API](https://ai.google.dev/gemini-api/docs/structured-output) with the action JSON schema and independently validates the response. Live paid Gemini calls were not made during development; SDK calls, schemas and provider errors are tested with mocks.

### Demo commands

Demo mode is a limited deterministic parser, with its commands shown beside the chat. It does not pretend to understand arbitrary language.

```text
I want to get good at C++ by December.
I need to study LeetCode for an hour every day.
I have a programming assignment due Friday.
I have class Monday and Wednesday from 1 to 3.
I want to work out four times per week.
Move my workout to tonight.
I don't want to study C++ right now.
I finished LeetCode early.
I spent two hours gaming.
I need to finish this assignment first.
Reschedule my week.
```

Defaults are returned explicitly. Ambiguous references ask for clarification instead of guessing. The C++ learning goal creates two actionable initial work packages. If several C++ tasks exist, use the task form to select one; Gemini can resolve an exact title or ask a follow-up question.

## Windows companion

Install CMake and Visual Studio's **Desktop development with C++** workload, then:

```powershell
cmake -S desktop-agent -B desktop-agent/build -A x64
cmake --build desktop-agent/build --config Release
ctest --test-dir desktop-agent/build -C Release --output-on-failure
.\desktop-agent\build\Release\daylight-agent.exe --self-test
.\desktop-agent\build\Release\daylight-agent.exe --probe
```

To actually monitor:

1. Generate a random token with `python -c "import secrets; print(secrets.token_hex(32))"`.
2. Set the same `AGENT_TOKEN` in the backend `.env` and your companion terminal environment. Restart the backend.
3. Enable **Activity monitoring** in the web Settings.
4. Explicitly start the companion with `--enable`:

```powershell
$env:AGENT_TOKEN = "the-token-you-generated"
.\desktop-agent\build\Release\daylight-agent.exe --enable --backend http://127.0.0.1:8000
```

Press **Ctrl+C** to stop. Disabling monitoring in Settings rejects reports and stops sampling when the companion next reports. There is no startup registration or hidden always-on service.

It samples every five seconds and reports every 30 seconds by default. A bounded in-memory buffer survives short outages, with capped retry backoff; stopping discards unsent data. No screenshots, keylogging, window titles, browser history or file paths are collected. Only loopback HTTP destinations are permitted, redirects are disabled and a token is required.

Associate optional executable names (e.g. `Code.exe`) with a task in its editor. Matching apps are weak context, never proof of work. Unknown activity is not treated as unrelated. After at least 15 minutes of idle/unassociated evidence, an unresolved session can produce a suggestion. Confirmation replans unconfirmed work; dismissal keeps the plan. Credit actual work in the session dialog before confirming a suggestion if you already completed part of it.

See [agent design and validation](DESKTOP_AGENT.md). The development machine lacked the MSVC workload; the executable was compiled and tested with Clang through a portable Zig C++ driver. The GitHub Windows job validates the normal MSVC build.

## API examples

```powershell
Invoke-RestMethod http://localhost:8000/api/tasks -Method Post -ContentType "application/json" -Body '{"title":"Review pointers","duration_minutes":60,"priority":4}'
Invoke-RestMethod http://localhost:8000/api/schedule/plan -Method Post -ContentType "application/json" -Body '{"days":7}'
Invoke-RestMethod http://localhost:8000/api/assistant -Method Post -ContentType "application/json" -Body '{"message":"I want to get good at C++ by December."}'
```

Use the returned task/session IDs to PATCH resources. Timestamps supplied to the API must have an explicit offset. All endpoints and schemas are documented at `/docs`; [API.md](API.md) includes resource and error behavior.

## Tests and builds

```powershell
# Repository root; after backend dependencies are installed
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m ruff format --check backend

cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npm audit --omit=dev
```

For real browser integration tests, run an API and frontend against an **isolated demo database**; the workflows create goals/tasks and complete a planned session:

```powershell
cd frontend
npx playwright install chromium
npm run test:e2e
# Or use an existing Chrome:
$env:CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
npm run test:e2e
```

To verify native HTTP ingestion without monitoring any real activity:

```powershell
.\.venv\Scripts\python.exe backend\scripts\agent_smoke.py desktop-agent\build\Release\daylight-agent.exe
```

This starts a temporary loopback backend/database and sends a synthetic unknown event. For a real PostgreSQL smoke test, migrate and seed a disposable PostgreSQL database, then run `python scripts/postgres_smoke.py` from `backend`.

CI runs backend tests, real PostgreSQL migrations and persistence, frontend checks/build, browser workflows and the Windows native build/CTest. Test results recorded in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) are local observations; CI itself has not been executed on GitHub yet.

