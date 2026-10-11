# REST API

Base URL: http://127.0.0.1:8000. Interactive OpenAPI: /docs. The Next.js server proxies /api/* to FastAPI, keeping backend URLs and Gemini secrets out of client configuration.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | /health | Database/preference readiness |
| GET | /api/system | Demo/Gemini configuration and activity connection status |
| GET, POST | /api/goals | List/create goals |
| PUT, DELETE | /api/goals/{id} | Replace/delete a goal; deletion keeps its tasks |
| GET, POST | /api/tasks | List/create tasks; creating replans the week |
| PATCH, DELETE | /api/tasks/{id} | Update/delete task and replan; deletion cascades its sessions |
| GET, PUT | /api/preferences | Read/replace validated preferences and replan |
| GET, POST | /api/obligations | List/create fixed events (classes, appointments, interviews) and replan |
| PUT, DELETE | /api/obligations/{id} | Edit/delete a fixed event and replan |
| GET | /api/sessions?start=...&end=... | Sessions overlapping a UTC interval, with category, goal subtitle and deadline |
| PATCH | /api/sessions/{id} | Lock/unlock, complete, skip or mark missed (skip/missed replans) |
| POST | /api/schedule/plan | Generate/persist a day or multi-day plan explicitly |
| GET | /api/overview?start=YYYY-MM-DD&days=1..42 | Coming up, goal progress, stats, briefs, deadlines and chat prompts for a range |
| POST | /api/assistant | Interpret a chat message and return a **proposal** (a dry run); nothing is saved yet |
| GET | /api/proposals/current | The proposal awaiting review, or the last applied one while it can still be undone |
| POST | /api/proposals/{id}/apply | Apply a pending proposal |
| POST | /api/proposals/{id}/discard | Discard a pending proposal |
| POST | /api/proposals/{id}/undo | Restore the plan from before an applied proposal, if nothing has changed since |
| GET, POST | /api/calendars | List connected calendar feeds (link hidden) / connect an .ics feed: `{"provider":"canvas","name":"","url":"https://…"}` (`canvas`, `google`, `outlook`, `apple`, `other`; `{"provider":"demo","url":"demo://canvas"}` for the built-in demo feed) |
| POST | /api/calendars/{id}/sync | Re-fetch a feed now; a failed fetch is recorded in `last_error` |
| DELETE | /api/calendars/{id} | Disconnect a feed and remove its imported events |
| POST | /api/demo/clear, /api/demo/populate | Demo mode only (`AI_MODE=demo` or `DEMO_NOW` set; otherwise 403): empty the planner, or replace everything with the sample week plus the demo Canvas feed. Preferences are kept. Shown as chips under the chat. |
| GET | /api/messages | Last 100 stored chat messages, each linked to its proposal when there is one |
| POST | /api/activity | Ingest a bounded idempotent event batch |
| GET | /api/suggestions | Pending activity suggestions |
| POST | /api/suggestions/{id}/decision | Confirm/dismiss suggested adaptation |

## Representative bodies

Task:
```json
{"title":"Review pointers","duration_minutes":90,"priority":4,"min_session_minutes":30,"max_session_minutes":90,"deadline":"2027-01-05T07:59:00Z","recurrence":"none","activity_apps":["Code.exe"]}
```

Tasks also take `category`: `focus` (default), `routine`, `personal` or `errand`.

Fixed recurring class (Monday=0):
```json
{"title":"Algorithms class","weekdays":[0,2],"start_time":"13:00","end_time":"15:00"}
```

One-off appointment shown under Coming up (`kind` is `commitment` by default, or `appointment`, `interview`, `personal`):
```json
{"title":"Dentist cleaning","kind":"appointment","weekdays":[2],"start_time":"08:30","end_time":"09:30","start_date":"2027-01-06","end_date":"2027-01-06"}
```

Plan:
```json
{"start_date":"2027-01-04","days":7}
```
Omit start_date for the current local day. Returns sessions, unscheduled work/reasons, solver_status and explanation.

Chat:
```json
{"message":"Move my workout to tonight.","plan":{"days":7}}
```
Returns reply, mode, defaults, needs_clarification and an optional `proposal`: title, `changes` (Moved/Shortened/Extended/Added/Removed/Kept rows), footer, and `preview.sessions` (the would-be schedule, each new session tagged in `change`). The proposal is computed by applying the batch in a transaction that is then rolled back. Apply commits exactly the previewed result (stored with the proposal) when nothing has changed since the preview, with no second solve; otherwise it re-runs the stored, validated batch and plans again. Either way it returns what actually changed; Undo restores a snapshot of goals, tasks, obligations, preferences, sessions and suggestions, and is refused (409) once anything else has changed. Provider output is never executed without service validation.

## Connected calendars

Feeds are fetched by the backend (15 s timeout, 5 MB cap, `webcal://` accepted), parsed with `icalendar` and `recurring-ical-events` from two weeks back to two months ahead, and refreshed when the planner loads if older than 15 minutes. Imported items are read-only and fixed: timed events are locked blocks planning works around (they may overlap anything), zero-length items such as Canvas assignments (`UID: event-assignment-…`) are deadlines in the DUE strip and Coming up, and date-only items are all-day notes. Canvas titles like `Lab 4 [CS 241]` keep the course separately. Changes replan the week. Feed links are secrets: they stay on the backend and the API only returns a hint.

## Automatic upkeep

The interface has no "generate plan" or "mark done" controls, so the API does this itself:

- Creating, editing or deleting tasks and obligations, changing preferences, or skipping a session replans the next seven days in the same transaction.
- Reading `/api/overview` or `/api/sessions` first credits planned work whose time has passed as completed (after a 30-minute grace period, and never while an activity suggestion is pending, when monitoring is on), then replans if the planned horizon no longer covers the next seven days. Corrections ("I didn't do X") go through the assistant.

Complete part of a session:
```json
{"status":"completed","actual_minutes":30}
```
Credit is idempotent. Omit actual_minutes to credit the reserved duration. Actual minutes cannot exceed the session. Recurring task status remains pending until the user retires the routine.

Activity (send X-Agent-Token; monitoring must already be enabled):
```json
{"events":[{"id":"00000000-0000-0000-0000-000000000001","starts_at":"2027-01-04T20:00:00Z","ends_at":"2027-01-04T20:00:30Z","state":"active","app_name":"Code.exe","idle_seconds":0}]}
```
Intervals must be positive, at most five minutes, within the previous 24 hours, and non-overlapping. Duplicate UUIDs are acknowledged without duplicate evidence. Active/idle/unknown are distinct; executable basenames only.

Suggestion:
```json
{"decision":"confirm"}
```
Confirming an unlocked unresolved session marks its unconfirmed work missed and replans. Dismissal keeps it planned. An already resolved decision is idempotent. For partial progress, credit that progress in the session first; stale suggestions can be dismissed. The interface shows pending suggestions as check-in cards in the assistant panel.

## Errors and transactions

- 401: Missing/mismatched configured agent token.
- 403: Monitoring disabled.
- 404: Unknown referenced resource.
- 409: Protected block conflict, invalid session transition, overlap evidence or infeasible/unknown solve.
- 422: Schema/semantic validation, naive timestamps, invalid local windows or excessive horizon/workload.
- 502: Invalid provider action output.
- 503: Missing configuration, unavailable provider or database.

Resource mutations and action-driven schedule replacement commit before an HTTP success response. Invalid batches roll back. Responses never contain keys or raw provider exceptions. This API intentionally has no multi-user authentication and should remain bound to loopback.
