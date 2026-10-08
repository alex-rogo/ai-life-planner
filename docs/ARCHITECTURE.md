# Architecture and implementation plan

This repository contains a local-first, single-user modular monolith. FastAPI owns all state; React renders its REST resources. Gemini proposes typed actions, a service validates and applies them, and CP-SAT determines feasible work intervals. The C++ companion submits coarse application/idle activity only after explicit opt-in.

Implementation order:
1. Relational models, migrations, CRUD and validated preferences.
2. Deterministic 15-minute scheduler and transactional schedule persistence.
3. Typed AI action pipeline, deterministic demo commands and adaptive replanning.
4. Responsive dashboard, calendar, task/goal management, assistant and settings.
5. Native Windows monitoring and confirmed activity suggestions.
6. Integration tests, CI, reproducible local setup and portfolio documentation.

PostgreSQL is the normal runtime database. SQLite is supported for repeatable tests and an optional standalone demo. UTC timestamps cross every boundary; IANA user timezones determine calendar days, sleep and working windows. Fixed obligations can fall outside flexible-work availability. Completed, locked and in-progress sessions are never moved by the solver. Historical missed/skipped intervals remain in the audit trail but do not block future work.

Mutating services acquire the singleton preference row with SELECT FOR UPDATE on PostgreSQL, serializing schedule mutations across requests. All action batches and schedule replacement commit together or roll back. There are no queues or background workers: activity suggestions are evaluated when events arrive and adaptation occurs only after user confirmation.
