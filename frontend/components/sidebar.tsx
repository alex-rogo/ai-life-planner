"use client";
import { useState } from "react";
import { dayLabel } from "../lib/time";
import { GOAL_COLORS, KIND } from "../lib/calendar";
import type { Overview, Upcoming, UpcomingKind, View } from "../lib/types";

const FILTERS: { kind: UpcomingKind | "All"; label: string }[] = [
  { kind: "All", label: "All" }, { kind: "Appointment", label: "Appointments" },
  { kind: "Project", label: "Projects" }, { kind: "Assignment", label: "Assignments" }, { kind: "Interview", label: "Interviews" },
];

interface Props {
  view: View; overview: Overview | null;
  onAddEvent: () => void; onAddGoal: () => void; onOpenGoal: (id: string) => void; onOpenItem: (item: Upcoming) => void;
}

export default function Sidebar({ view, overview, onAddEvent, onAddGoal, onOpenGoal, onOpenItem }: Props) {
  const [filter, setFilter] = useState<UpcomingKind | "All">("All");
  const items = (overview?.upcoming ?? []).filter(u => filter === "All" || u.kind === filter);
  return (
    <aside className="left" aria-label="Coming up and goals">
      <section className="card panel" aria-label="Coming up">
        <div className="panel-head">
          <h2>Coming up</h2>
          <button className="add" aria-label="Add something important" onClick={onAddEvent}>+</button>
        </div>
        <div role="tablist" aria-label="Filter what's coming up" className="pills">
          {FILTERS.map(f => <button key={f.kind} role="tab" aria-selected={filter === f.kind} className="pill" onClick={() => setFilter(f.kind)}>{f.label}</button>)}
        </div>
        <div>
          {items.map(u => {
            const k = KIND[u.kind], editable = !!(u.obligation_id || u.goal_id);
            const content = (
              <>
                <div className="date-chip" style={{ background: k.tint }}>
                  <span className="dow" style={{ color: k.color }}>{dayLabel(u.date, { weekday: "short" }).toUpperCase()}</span>
                  <span className="num">{Number(u.date.slice(8))}</span>
                </div>
                <div className="stack">
                  <span className="eyebrow" style={{ color: k.color }}>{u.kind} · {u.when}</span>
                  <span className="title-sm">{u.title}</span>
                  <span className="meta">{u.meta}</span>
                  {u.note && <span className="note">{u.note}</span>}
                </div>
              </>
            );
            const key = `${u.kind}-${u.title}-${u.date}`;
            return editable
              ? <button key={key} className="upcoming" onClick={() => onOpenItem(u)} aria-label={`Edit ${u.kind.toLowerCase()}: ${u.title}, ${u.when}. ${u.meta}`}>{content}</button>
              : <div key={key} className="upcoming">{content}</div>;
          })}
          {overview && !items.length && (
            <p className="empty">{filter === "All" ? "Nothing important in the next three weeks. Add an appointment, interview or deadline with +." : `No ${FILTERS.find(f => f.kind === filter)!.label.toLowerCase()} coming up.`}</p>
          )}
        </div>
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
