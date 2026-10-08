# Scheduling design

The planner receives relational state and a bounded horizon. It creates work units, computes feasible start domains, solves CP-SAT and replaces only movable reservations after a feasible solution exists. Domain computation and optimization are deterministic for the same input and solver parameters; a wall-clock solve limit can still return different feasible incumbents across machines.

## Hard constraints

- A work unit uses consecutive 15-minute slots. Finite work is partitioned into balanced sessions within minimum/maximum bounds.
- Starts cannot precede current time, creation time or an explicit not-before constraint. Ends cannot exceed a task deadline or the horizon.
- Every occupied minute must be within local availability and outside the sleep window.
- A session must fit within one local calendar day. Local day boundaries convert to UTC, handling daylight saving changes.
- Candidate starts that overlap any fixed, locked, completed or in-progress interval are removed. Fixed appointments retain exact, potentially non-quarter-hour timestamps.
- CP-SAT optional intervals use `AddNoOverlap` for flexible work.
- Overlapping protected blocks and constraint changes conflicting with future locked sessions return HTTP 409, retaining the existing schedule.

Fixed obligations may be outside flexible availability/sleep, since a user-declared appointment is authoritative. Changing its definition is explicit CRUD. In-progress and historical completed sessions are immutable to optimization.

## Objective

First maximize **scheduled minutes × (priority + 1)**. Optional work enables useful partial plans when capacity is insufficient. The coverage coefficient exceeds the bounded total secondary penalty, preventing preference weights from outweighing weighted coverage.

Secondary terms:

| Term | Default weight | Behavior |
| --- | ---: | --- |
| Early work | Task priority | Penalizes later starts more strongly for higher priority |
| Preferred hours | 3 | Penalizes distance before/after that day's preferred window |
| Stability | 8 | Penalizes displacement from matched prior reservations |
| Recovery breaks | 10 | Penalizes insufficient gaps when either work unit is at least 60 minutes |
| Context | 5 | Penalizes adjacent sessions from different tasks |
| Weekly spread | 20 | Penalizes weekly occurrences on the same day |

The secondary terms use normalization constants (12 for time-related preferences; 100 for spread) to give reasonable effects at quarter-hour resolution. They are heuristic product choices, not learned weights. Adjust weights in Settings. Recovery and context penalties are pairwise proxies; they do not measure human fatigue or semantic similarity.

A small per-day selector model keeps local preferred-hour costs compact. It avoids a large per-start Boolean/lookup model. Prior reservation hints help find a stable incumbent.

## Recurrences and accounting

One-time tasks use estimated minus user-credited minutes minus protected planned reservations. Daily tasks use a local-day target; weekly tasks use duration × sessions per week for each Monday-based week intersecting the horizon. Existing completed credit and protected reservations reduce those targets. Finite residuals round up to the next slot; work too short to meet the minimum is reported rather than squeezed into an invalid session.

A recurring occurrence normally fits one session. Partial completion may create a make-up session, so weekly session count is a planning target rather than a guarantee of exactly N distinct occurrence IDs.

Plans count reservations outside the requested horizon to avoid double-booking the same remaining work. Historical unresolved reservations require an explicit completion/missed/skipped decision; the system never infers missed work simply because time has passed.

## Adaptation and failure

Completed and running intervals, fixed obligations and user locks are retained. Unchanged reservations retain their UUIDs, keeping associated suggestion identities stable. Movable sessions have costs based on earlier matched session times.

A skipped/missed session has no completion credit and is retained as historical context. It frees future capacity; the remaining task is included in replanning. An activity suggestion makes no mutation until a user confirms it. Unknown application attribution is insufficient evidence.

No legal start: return a specific constraint/capacity reason. Capacity exhausted: return the weighted-work allocation reason. Conflicting protected blocks: return 409 without replacement. Solver UNKNOWN/INFEASIBLE: no fabricated schedule and no state commit for the calling action batch.

Solve limits are eight seconds, one search worker, fixed random seed, maximum 100 work units and 14 calendar days. FEASIBLE is a valid plan; only OPTIMAL proves the objective optimum. This is a planning tool, not an assurance that every goal will fit.

Reference: [OR-Tools scheduling](https://developers.google.com/optimization/scheduling/job_shop).
