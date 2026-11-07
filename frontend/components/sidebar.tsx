"use client";
import { useState } from "react";
import { useArrivals } from "../lib/arrivals";
import { dayLabel } from "../lib/time";
import { GOAL_COLORS, KIND } from "../lib/calendar";
import type { Overview, Upcoming, UpcomingKind, View } from "../lib/types";

const FILTERS: { kind: UpcomingKind | "All"; label: string }[] = [
  { kind: "All", label: "All" }, { kind: "Appointment", label: "Appointments" },
  { kind: "Project", label: "Projects" }, { kind: "Assignment", label: "Assignments" }, { kind: "Interview", label: "Interviews" },
];

interface Props {
  view: View; overview: Overview | null; today: string; busy: boolean;
  onCheck: (item: Upcoming, done: boolean) => void;
  onAddEvent: () => void; onAddGoal: () => void; onOpenGoal: (id: string) => void; onOpenItem: (item: Upcoming) => void;
}

export default function Sidebar({ view, overview, today, busy, onCheck, onAddEvent, onAddGoal, onOpenGoal, onOpenItem }: Props) {
  const [filter, setFilter] = useState<UpcomingKind | "All">("All");
  // Checks show at once; they belong to the overview they were made on, so fresh data replaces them.
  const [flips, setFlips] = useState<{ overview: Overview | null; done: Record<string, boolean> }>({ overview: null, done: {} });
  const isDone = (u: Upcoming) => (flips.overview === overview ? flips.done[u.key] : undefined) ?? u.done;
  const toggle = (u: Upcoming) => {
    const done = !isDone(u);
    setFlips(f => ({ overview, done: { ...(f.overview === overview ? f.done : {}), [u.key]: done } }));
    onCheck(u, done);
  };
  const all = overview?.upcoming ?? [];
  // Everything that is new since the last refresh grows into the list (whatever the filter).
  const fresh = useArrivals(all.map(u => u.key), "tasks", !!overview);
  const shown = all.filter(u => filter === "All" || u.kind === filter);
  const label = filter === "All" ? "" : `${FILTERS.find(f => f.kind === filter)!.label.toLowerCase()} `;
  const groups: { name: string; items: Upcoming[]; empty: string }[] = [
    { name: "Today", items: shown.filter(u => u.date <= today), empty: filter === "All" ? "Nothing due today." : `No ${label}today.` },
    { name: "Upcoming", items: shown.filter(u => u.date > today), empty: filter === "All" ? "Nothing important in the next three weeks. Add an appointment, interview or deadline with +." : `No ${label}coming up.` },
  ];
  const row = (u: Upcoming) => {
    const k = KIND[u.kind], editable = !!(u.obligation_id || u.goal_id), done = isDone(u);
    const content = (
      <>
        <div className="date-chip" style={{ background: k.tint }}>
          <span className="dow" style={{ color: k.color }}>{dayLabel(u.date, { weekday: "short" }).toUpperCase()}</span>
          <span className="num">{Number(u.date.slice(8))}</span>
        </div>
        <div className="stack">
          <span className="eyebrow" style={{ color: k.color }}>{u.kind} · {u.when}</span>
          <span className="title-sm strike">{u.title}</span>
          <span className="meta">{u.meta}</span>
          {u.note && <span className="note">{u.note}</span>}
        </div>
      </>
    );
    return (
      <div key={u.key} className={`task-item${done ? " done" : ""}${fresh.has(u.key) ? " arrive" : ""}`}>
        <button className="check" role="checkbox" aria-checked={done} aria-label={`${done ? "Uncheck" : "Check off"} ${u.title}`} disabled={busy} onClick={() => toggle(u)}>
          <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
        </button>
        {editable
          ? <button className="upcoming" onClick={() => onOpenItem(u)} aria-label={`Edit ${u.kind.toLowerCase()}: ${u.title}, ${u.when}. ${u.meta}`}>{content}</button>
          : <div className="upcoming">{content}</div>}
      </div>
    );
  };
  return (
    <aside className="left" aria-label="Tasks and goals">
      <section className="card panel" aria-label="Tasks">
        <div className="panel-head">
          <h2>Tasks</h2>
          <button className="add" aria-label="Add something important" onClick={onAddEvent}>+</button>
        </div>
        <div role="tablist" aria-label="Filter tasks by category" className="pills">
          {FILTERS.map(f => <button key={f.kind} role="tab" aria-selected={filter === f.kind} className="pill" onClick={() => setFilter(f.kind)}>{f.label}</button>)}
        </div>
        {groups.map(g => (
          <div key={g.name} className="task-group" role="group" aria-label={g.name}>
            <div className="group-head"><h3>{g.name}</h3>{overview && <span className="count">{g.items.filter(u => !isDone(u)).length} left</span>}</div>
            {g.items.map(row)}
            {overview && !g.items.length && <p className="empty">{g.empty}</p>}
          </div>
        ))}
      </section>
      <section className="card panel" style={{ gap: 14 }}>
        <div className="panel-head">
          <h2>{view === "week" ? "Goals this week" : "Goals"}</h2>
          <button className="add" aria-label="Add goal" onClick={onAddGoal}>+</button>
        </div>
        {overview?.goals.map((g, i) => (
          <button key={g.id} className="goal" onClick={() => onOpenGoal(g.id)} aria-label={`${g.title}: ${g.progress}. ${g.meta}`}>
            <div className="goal-row"><span className="title-sm">{g.title}</span><span className="goal-pct">{g.progress}</span></div>
            <div className="track" style={{ width: "100%" }}><div style={{ width: `${g.pct}%`, background: GOAL_COLORS[i % GOAL_COLORS.length] }} /></div>
            <span className="meta">{g.meta}</span>
          </button>
        ))}
        {overview && !overview.goals.length && <p className="empty">No goals yet. Add one, or tell Tomo what you’re working toward.</p>}
      </section>
    </aside>
  );
}
