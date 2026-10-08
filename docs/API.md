# REST API

Base URL: http://127.0.0.1:8000. Interactive OpenAPI: /docs. The Next.js server proxies /api/* to FastAPI, keeping backend URLs and Gemini secrets out of client configuration.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | /health | Database/preference readiness |
| GET | /api/system | Demo/Gemini configuration and activity connection status |
| GET, POST | /api/goals | List/create goals |
| PUT, DELETE | /api/goals/{id} | Replace/delete a goal; deletion keeps its tasks |
| GET, POST | /api/tasks | List/create tasks |
| PATCH, DELETE | /api/tasks/{id} | Update/delete task; deletion cascades its sessions |
| GET, PUT | /api/preferences | Read/replace validated preferences |
| GET, POST | /api/obligations | List/create recurring fixed obligations |
| PUT, DELETE | /api/obligations/{id} | Edit/delete fixed obligation |
| GET | /api/sessions?start=...&end=... | Read sessions overlapping a UTC interval |
| PATCH | /api/sessions/{id} | Lock/unlock, complete, skip or mark missed |
| POST | /api/schedule/plan | Generate/persist a day or multi-day plan |
| POST | /api/assistant | Interpret and transactionally apply a chat action batch |
| GET | /api/messages | Last 100 stored chat messages |
| POST | /api/activity | Ingest a bounded idempotent event batch |
| GET | /api/suggestions | Pending activity suggestions |
| POST | /api/suggestions/{id}/decision | Confirm/dismiss suggested adaptation |

## Representative bodies

Task:
```json
{"title":"Review pointers","duration_minutes":90,"priority":4,"min_session_minutes":30,"max_session_minutes":90,"deadline":"2027-01-05T07:59:00Z","recurrence":"none","activity_apps":["Code.exe"]}
```

Fixed recurring class (Monday=0):
```json
{"title":"Algorithms class","weekdays":[0,2],"start_time":"13:00","end_time":"15:00"}
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
Returns reply, mode, defaults, created_ids, needs_clarification and an optional plan. Provider output is never executed without service validation.

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
Confirming an unlocked unresolved session marks its unconfirmed work missed and replans. Dismissal keeps it planned. An already resolved decision is idempotent. For partial progress, credit that progress in the session first and generate a plan; stale suggestions can be dismissed.

## Errors and transactions

- 401: Missing/mismatched configured agent token.
- 403: Monitoring disabled.
- 404: Unknown referenced resource.
- 409: Protected block conflict, invalid session transition, overlap evidence or infeasible/unknown solve.
- 422: Schema/semantic validation, naive timestamps, invalid local windows or excessive horizon/workload.
- 502: Invalid provider action output.
- 503: Missing configuration, unavailable provider or database.

Resource mutations and action-driven schedule replacement commit before an HTTP success response. Invalid batches roll back. Responses never contain keys or raw provider exceptions. This API intentionally has no multi-user authentication and should remain bound to loopback.
