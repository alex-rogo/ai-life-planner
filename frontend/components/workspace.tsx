"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bell, PanelLeft, ArrowUp, ArrowRight, CalendarDays, Check, CheckCheck, ChevronLeft, ChevronRight, Circle, Clock3, LayoutDashboard, ListTodo, LoaderCircle, LockKeyhole, Pencil, Plus, RefreshCw, Settings2, Sparkles, Sun, Target, Trash2, X } from "lucide-react";
import { api } from "../lib/api";
import { addDays, clock, dateKey, dayLabel, duration, hours, zonedISO } from "../lib/time";
import type { ChatResult, Goal, Message, Obligation, PlanResult, Preferences, Session, Suggestion, SystemStatus, Task, Unscheduled } from "../lib/types";
import Calendar from "./calendar";
import SessionCard from "./session-card";
import TaskForm from "./task-form";
import Settings from "./settings";
import MiniCalendar from "./mini-calendar";
import Reminders from "./Reminders";

type View = "dashboard" | "calendar" | "tasks" | "assistant" | "settings" | "reminders";
const navigation = [
  { href: "/", view: "dashboard", label: "Home", icon: LayoutDashboard },
  { href: "/calendar", view: "calendar", label: "Calendar", icon: CalendarDays },
  { href: "/tasks", view: "tasks", label: "Tasks", icon: ListTodo },
  { href: "/reminders", view: "reminders", label: "Reminders", icon: Bell },
  { href: "/assistant", view: "assistant", label: "Assistant", icon: Sparkles },
  { href: "/settings", view: "settings", label: "Settings", icon: Settings2 },
];
const titles = { dashboard: "Home", calendar: "Calendar", tasks: "Tasks", assistant: "Assistant", settings: "Settings", reminders: "Reminders" };

export default function Workspace({ view }: { view: View }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [obligations, setObligations] = useState<Obligation[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [unscheduled, setUnscheduled] = useState<Unscheduled[]>([]);
  const [selected, setSelected] = useState<Session | null>(null);
  const [editingTask, setEditingTask] = useState<Task | null | undefined>(undefined);
  const [editingGoal, setEditingGoal] = useState<Goal | null | undefined>(undefined);
  const [day, setDay] = useState("");
  const [calendarMode, setCalendarMode] = useState<"day" | "week">("day");
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [showFlexible, setShowFlexible] = useState(true);
  const [showFixed, setShowFixed] = useState(true);
  const [horizon, setHorizon] = useState(7);
  const [filter, setFilter] = useState("pending");
  const [draft, setDraft] = useState("");
  const [now, setNow] = useState(() => new Date());

  const refresh = useCallback(async () => {
    const [t, g, s, p, o, m, status, suggestions] = await Promise.all([
      api<Task[]>("/tasks"), api<Goal[]>("/goals"), api<Session[]>("/sessions"),
      api<Preferences>("/preferences"), api<Obligation[]>("/obligations"),
      api<Message[]>("/messages"), api<SystemStatus>("/system"), api<Suggestion[]>("/suggestions"),
    ]);
    setTasks(t); setGoals(g); setSessions(s); setPreferences(p); setObligations(o);
    setMessages(m); setSystem(status); setSuggestions(suggestions.filter(s => s.status === "pending"));
    setDay(current => current || dateKey(new Date(), p.timezone)); setError("");
  }, []);
  useEffect(() => {
    let active = true;
    Promise.resolve().then(refresh).catch(err => { if (active) setError(err.message); }).finally(() => { if (active) setLoading(false); });
    const tick = setInterval(() => setNow(new Date()), 30000);
    return () => { active = false; clearInterval(tick); };
  }, [refresh]);
  useEffect(() => {
    const poll = setInterval(() => { if (!busy) refresh().catch(() => {}); }, 30000);
    return () => clearInterval(poll);
  }, [busy, refresh]);

  async function mutate(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); await refresh(); setNotice(success); }
    catch (err) { setError(err instanceof Error ? err.message : "Something went wrong."); }
    finally { setBusy(false); }
  }
  async function generate() {
    await mutate(async () => {
      const result = await api<PlanResult>("/schedule/plan", "POST", { start_date: day, days: horizon });
      setUnscheduled(result.unscheduled);
    }, "Plan updated.");
  }
  async function send(event: React.FormEvent) {
    event.preventDefault(); if (!draft.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<ChatResult>("/assistant", "POST", { message: draft, plan: { start_date: day, days: horizon } });
      if (result.plan) setUnscheduled(result.plan.unscheduled);
      setDraft(""); await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not reach assistant."); }
    finally { setBusy(false); }
  }
  const timezone = preferences?.timezone || "America/Los_Angeles";
  const today = dateKey(now, timezone);
  const todaySessions = sessions.filter(s => dateKey(s.starts_at, timezone) === today);
  const workToday = todaySessions.filter(s => s.task_id);
  const completedToday = workToday.filter(s => s.status === "completed");
  const minutesPlanned = workToday.filter(s => s.status === "planned").reduce((n, s) => n + duration(s), 0);
  const current = todaySessions.find(s => s.status === "planned" && new Date(s.starts_at) <= now && new Date(s.ends_at) > now);
  const next = todaySessions.find(s => s.status === "planned" && new Date(s.starts_at) > now);
  const pending = tasks.filter(t => t.status === "pending");
  const days = Array.from({ length: calendarMode === "week" ? 7 : 1 }, (_, i) => addDays(day || today, i));
  const visibleTasks = tasks.filter(t => filter === "all" || t.status === filter);

  const assistant = system && (<div className="chat-layout"><section className="panel chat-panel"><div className="panel-heading"><div className="chat-identity"><span><Sparkles size={21} /></span><div><h2>Assistant</h2><p>{system.ai_mode === "demo" ? "Demo parser · sample commands only" : `Gemini · ${system.gemini_model}`}</p></div></div><span className="mode-badge">{system.ai_mode}</span></div><div className="chat-messages" aria-live="polite">{messages.length ? messages.map(m => <div key={m.id} className={`chat-message ${m.role}`}><small>{m.role === "user" ? "You" : m.mode === "demo" ? "AI Planner · demo" : "AI Planner · Gemini"}</small><p>{m.content}</p></div>) : <div className="chat-welcome"><span><Sparkles size={34} /></span><h2>Plan or adjust your schedule</h2><p>Add tasks, move sessions, or replan your week.</p><small>{system.ai_mode === "demo" ? "This demo uses limited deterministic patterns. Start with a sample on the right." : "Your assistant interprets requests. A constraint solver builds the schedule."}</small></div>}{busy && <div className="chat-message assistant"><LoaderCircle size={16} className="spin" />Interpreting and checking your plan…</div>}</div><form className="chat-composer" onSubmit={send}><textarea aria-label="Message your assistant" placeholder="Message…" value={draft} maxLength={4000} onChange={e => setDraft(e.target.value)} rows={2} /><button className="button primary" aria-label="Send message" disabled={busy || !draft.trim()}><ArrowUp size={20} /></button></form><p className="chat-footer">Actions are validated before they change your plan. Ambiguous requests ask for clarification.</p></section><aside className="stack"><section className="panel"><h2>Sample commands</h2><p className="muted">{system.ai_mode === "demo" ? "Exact sample commands for this demo" : "Try a goal, routine, or change of plans"}</p><div className="sample-commands">{system.demo_commands.map(command => <button key={command} onClick={() => setDraft(command)}>{command}<ArrowUp size={13} /></button>)}</div></section></aside></div>);

  return <div className={`app-shell view-${view} ${view === "calendar" && assistantOpen ? "with-assistant" : ""}`}>
    <aside className="sidebar">
      <Link className="brand" href="/"><span><PanelLeft size={21} /></span>AI Planner</Link>

      <nav>{navigation.map(item => <Link key={item.view} href={item.href} aria-label={item.label} aria-current={view === item.view ? "page" : undefined} className={view === item.view ? "active" : ""}><item.icon size={19} />{item.label}</Link>)}</nav>
      <MiniCalendar selected={day || today} today={today} onSelect={setDay} />
      <div className="sidebar-calendars"><h2>Calendars</h2><label><input type="checkbox" checked={showFlexible} onChange={e => setShowFlexible(e.target.checked)} />Tasks</label><label><input type="checkbox" checked={showFixed} onChange={e => setShowFixed(e.target.checked)} />Fixed commitments</label></div>
      <div className="sidebar-bottom"><span className="status-dot online" /><span>{timezone.replaceAll("_", " ")}</span></div>
    </aside>
    <main>
      <header className="topbar"><span>{navigation.find(n => n.view === view)?.label}</span><div><span className="date-pill">{dayLabel(today)}</span><button className="icon-button" aria-label="Refresh data" disabled={busy} onClick={() => mutate(refresh, "Updated from the backend.")}><RefreshCw size={17} /></button><span className="avatar">Y</span></div></header>
      <div className="page-content">
        <div className="page-heading"><h1>{titles[view]}</h1>{view === "calendar" && <button className="button secondary" aria-pressed={assistantOpen} onClick={() => setAssistantOpen(!assistantOpen)}><Sparkles size={16} />Assistant</button>}{view === "tasks" && <button className="button primary" onClick={() => setEditingTask(null)}><Plus size={16} />New task</button>}</div>
        {error && <div className="alert error" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></button></div>}
        {notice && <div className="alert success" role="status"><Check size={17} /><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice("")}><X size={16} /></button></div>}
        {loading ? <div className="loading"><LoaderCircle className="spin" size={26} /><p>Opening your workspace…</p></div> : !preferences || !system ? <section className="panel empty"><h2>The backend needs your attention</h2><p>Start FastAPI and apply the database migrations, then refresh.</p><button className="button primary" onClick={() => mutate(refresh, "Connected.")}>Try again</button></section> : <>
          {suggestions.length > 0 && <section className="suggestions">{suggestions.map(s => <div className="suggestion" key={s.id}><Sparkles size={20} /><div><strong>Suggested change</strong><p>{s.message}</p></div><button className="button secondary" disabled={busy} onClick={() => mutate(async () => { const result = await api<{ plan: PlanResult | null }>(`/suggestions/${s.id}/decision`, "POST", { decision: "confirm" }); if (result.plan) setUnscheduled(result.plan.unscheduled); }, "Confirmed and replanned remaining work.")}>Reschedule</button><button className="icon-button" aria-label="Dismiss suggestion" disabled={busy} onClick={() => mutate(() => api(`/suggestions/${s.id}/decision`, "POST", { decision: "dismiss" }), "Suggestion dismissed.")}><X size={17} /></button></div>)}</section>}
          {view === "calendar" && <section className="plan-toolbar" aria-label="Plan schedule"><div className="plan-fields"><label><span>Start date</span><input aria-label="Plan start date" type="date" value={day} onChange={e => setDay(e.target.value)} /></label><label><span>Range</span><select aria-label="Planning horizon" value={horizon} onChange={e => setHorizon(Number(e.target.value))}><option value={1}>One day</option><option value={7}>Seven days</option><option value={14}>Two weeks</option></select></label></div><button className="button primary" disabled={busy || !day} onClick={generate}>{busy ? <LoaderCircle className="spin" size={16} /> : <CalendarDays size={16} />}Plan schedule</button></section>}
          {unscheduled.length > 0 && <details className="capacity-note" open><summary>{hours(unscheduled.reduce((n, u) => n + u.minutes, 0))} of work needs more space</summary>{unscheduled.map((u, i) => <p key={i}><strong>{u.title} · {hours(u.minutes)}</strong> — {u.reason}</p>)}</details>}
          {view === "dashboard" && <>
            <div className="stats-grid"><div className="stat"><span><Clock3 size={18} />Remaining today</span><strong>{hours(minutesPlanned)}</strong><small>Flexible work remaining today</small></div><div className="stat"><span><CheckCheck size={18} />Completed</span><strong>{completedToday.length}<em> / {workToday.length}</em></strong><small>Work sessions completed</small></div><div className="stat"><span><Target size={18} />Pending tasks</span><strong>{pending.length}</strong><small>Pending tasks across {goals.length} goals</small></div></div>
            <div className="dashboard-grid"><div className="stack">
              <section className="focus-panel"><div className="focus-label"><span className="status-dot online" />{current ? "CURRENT SESSION" : next ? "UP NEXT" : "NO UPCOMING SESSION"}</div><h2>{current?.title || next?.title || "No sessions scheduled"}</h2><p>{current ? `${clock(current.starts_at, timezone)} – ${clock(current.ends_at, timezone)}` : next ? `${clock(next.starts_at, timezone)} · ${hours(duration(next))} scheduled.` : "Add a task or tell your assistant what you want to achieve."}</p><div>{current || next ? <button className="button focus-button" onClick={() => setSelected(current || next || null)}>View session<ArrowRight size={16} /></button> : <Link className="button focus-button" href="/assistant">Open assistant<ArrowRight size={16} /></Link>}<span className="focus-art"><Sun size={92} strokeWidth={1} /></span></div></section>
              <section className="panel"><div className="panel-heading"><div><h2>Today’s schedule</h2><p>{dayLabel(today, { weekday: "long", month: "long", day: "numeric" })}</p></div><Link className="text-link" href="/calendar">Full calendar<ArrowRight size={14} /></Link></div><div className="legend"><span><i className="flexible-dot" />Flexible work</span><span><i className="fixed-dot" />Fixed obligation</span></div>{todaySessions.length ? todaySessions.map(s => <SessionCard key={s.id} session={s} timezone={timezone} onSelect={setSelected} />) : <div className="empty compact"><CalendarDays size={30} /><h3>No sessions today</h3><p>Open Calendar to place your tasks.</p></div>}</section>
            </div><div className="stack"><section className="panel"><div className="panel-heading"><h2>Upcoming tasks</h2><Link className="text-link" href="/tasks">View all<ArrowRight size={14} /></Link></div>{pending.length ? pending.slice(0, 5).map(t => <div className="radar-task" key={t.id}><span className={`priority-mark p${t.priority}`} /><div><strong>{t.title}</strong><small>{t.deadline ? `Due ${dayLabel(dateKey(t.deadline, timezone))}` : t.recurrence === "daily" ? "Every day" : t.recurrence === "weekly" ? `${t.sessions_per_week} times a week` : "No deadline"} · {hours(t.duration_minutes)}</small></div><span className="priority-tag">P{t.priority}</span></div>) : <p className="muted">No pending tasks.</p>}<button className="button full secondary" onClick={() => setEditingTask(null)}><Plus size={16} />Add a task</button></section>
            </div></div>
          </>}
          {view === "calendar" && <section className="panel calendar-panel"><div className="panel-heading"><div><h2>{dayLabel(day, { month: "long", year: "numeric" })}</h2><p>{timezone}</p></div><div className="calendar-controls"><button className="icon-button" aria-label="Previous period" onClick={() => setDay(addDays(day, calendarMode === "week" ? -7 : -1))}><ChevronLeft size={18} /></button><button className="button secondary" onClick={() => setDay(today)}>Today</button><button className="icon-button" aria-label="Next period" onClick={() => setDay(addDays(day, calendarMode === "week" ? 7 : 1))}><ChevronRight size={18} /></button><div className="segmented"><button className={calendarMode === "day" ? "active" : ""} onClick={() => setCalendarMode("day")}>Day</button><button className={calendarMode === "week" ? "active" : ""} onClick={() => setCalendarMode("week")}>Week</button></div></div></div><div className="legend"><span><i className="flexible-dot" />Flexible work</span><span><i className="fixed-dot" />Fixed obligation</span><span>Click a block to update its status.</span></div><Calendar days={days} sessions={sessions.filter(s => s.obligation_id ? showFixed : showFlexible)} timezone={timezone} onSelect={setSelected} /></section>}
          {view === "tasks" && <>
            <div className="section-heading"><h2>Goals <span className="count">{goals.length}</span></h2><button className="button secondary" onClick={() => setEditingGoal(null)}><Plus size={16} />New goal</button></div>
            <div className="goals-grid">{goals.length ? goals.map(g => {
              const related = tasks.filter(t => t.goal_id === g.id); const done = related.filter(t => t.status === "completed").length;
              return <section className="goal-card" key={g.id}><div className="goal-top"><span className="goal-icon"><Target size={21} /></span><div><button className="icon-button" aria-label={`Edit ${g.title}`} onClick={() => setEditingGoal(g)}><Pencil size={15} /></button><button className="icon-button danger" aria-label={`Delete ${g.title}`} onClick={() => mutate(() => api(`/goals/${g.id}`, "DELETE"), "Goal deleted; tasks kept.")}><Trash2 size={15} /></button></div></div><h3>{g.title}</h3><p>{g.description || "No description"}</p><div className="goal-progress"><span style={{ width: `${related.length ? done / related.length * 100 : 0}%` }} /></div><small>{done} of {related.length} tasks complete{g.deadline ? ` · Due ${dayLabel(dateKey(g.deadline, timezone))}` : ""}</small></section>;
            }) : <section className="panel empty"><Target size={28} /><h3>No goals yet</h3><p>Create a goal here or through the assistant.</p></section>}</div>
            <section className="panel"><div className="panel-heading"><h2>Tasks</h2></div><div className="task-filter segmented">{["pending", "completed", "all"].map(f => <button key={f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>{f === "all" ? "All tasks" : f}</button>)}</div>
              {visibleTasks.length ? visibleTasks.map(t => <div className={`task-row ${t.status}`} key={t.id}><button className="complete-button" aria-label={`Mark ${t.title} ${t.status === "completed" ? "pending" : "complete"}`} disabled={busy} onClick={() => mutate(() => api(`/tasks/${t.id}`, "PATCH", { status: t.status === "completed" ? "pending" : "completed" }), "Task status updated.")}>{t.status === "completed" ? <Check size={17} /> : <Circle size={20} />}</button><div className="task-info"><strong>{t.title}</strong><small>{hours(t.duration_minutes)} · {t.recurrence === "none" ? `${t.completed_minutes}m logged` : t.recurrence === "daily" ? "Daily" : `${t.sessions_per_week}/week`}{t.deadline ? ` · Due ${dayLabel(dateKey(t.deadline, timezone))}` : ""}{t.goal_id ? ` · ${goals.find(g => g.id === t.goal_id)?.title || "Goal"}` : ""}</small></div><span className="priority-tag">P{t.priority}</span><button className="icon-button" aria-label={`Edit ${t.title}`} onClick={() => setEditingTask(t)}><Pencil size={16} /></button><button className="icon-button danger" aria-label={`Delete ${t.title}`} disabled={busy} onClick={() => mutate(() => api(`/tasks/${t.id}`, "DELETE"), "Task deleted.")}><Trash2 size={16} /></button></div>) : <div className="empty compact"><ListTodo size={28} /><h3>No {filter === "all" ? "" : filter} tasks.</h3><p>Use the task form or describe your goal to the assistant.</p></div>}
            </section>
          </>}
          {view === "assistant" && assistant}
          {view === "reminders" && <Reminders />}
          {view === "settings" && <Settings key={JSON.stringify(preferences)} preferences={preferences} obligations={obligations} system={system} refresh={refresh} mutate={mutate} />}
        </>}

      </div>
    </main>
    {view === "calendar" && assistantOpen && <aside className="assistant-dock"><button className="icon-button dock-close" aria-label="Close assistant" onClick={() => setAssistantOpen(false)}><X size={18} /></button>{system && preferences ? assistant : <div className="empty">Connect to the backend to use the assistant.</div>}</aside>}
    {editingTask !== undefined && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="task-dialog-title"><div className="panel-heading"><h2 id="task-dialog-title">{editingTask ? "Edit task" : "New task"}</h2><button className="icon-button" aria-label="Close task form" onClick={() => setEditingTask(undefined)}><X size={19} /></button></div><TaskForm task={editingTask || undefined} goals={goals} timezone={timezone} onCancel={() => setEditingTask(undefined)} onSave={async values => { await api(editingTask ? `/tasks/${editingTask.id}` : "/tasks", editingTask ? "PATCH" : "POST", values); setEditingTask(undefined); await refresh(); setNotice("Task saved. Open Calendar to update your schedule."); }} /></section></div>}
    {editingGoal !== undefined && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="goal-dialog-title"><div className="panel-heading"><h2 id="goal-dialog-title">{editingGoal ? "Edit goal" : "New goal"}</h2><button className="icon-button" aria-label="Close goal form" onClick={() => setEditingGoal(undefined)}><X size={19} /></button></div><form className="form-grid" onSubmit={event => { event.preventDefault(); const form = new FormData(event.currentTarget); mutate(async () => { await api(editingGoal ? `/goals/${editingGoal.id}` : "/goals", editingGoal ? "PUT" : "POST", { title: form.get("title"), description: form.get("description"), deadline: form.get("deadline") ? zonedISO(String(form.get("deadline")), "23:59", timezone) : null }); setEditingGoal(undefined); }, "Goal saved."); }}><label className="span-two">Goal title<input name="title" required maxLength={200} defaultValue={editingGoal?.title} autoFocus /></label><label className="span-two">Description<textarea name="description" maxLength={4000} defaultValue={editingGoal?.description} rows={3} /></label><label className="span-two">Target date<input type="date" name="deadline" defaultValue={editingGoal?.deadline ? dateKey(editingGoal.deadline, timezone) : ""} /></label><button className="button primary span-two" disabled={busy}>Save goal</button></form></section></div>}
    {selected && <div className="modal-backdrop"><section className="modal session-detail" role="dialog" aria-modal="true" aria-labelledby="session-dialog-title"><div className="panel-heading"><span className="mode-badge">{selected.obligation_id ? "Fixed obligation" : selected.status}</span><button className="icon-button" aria-label="Close session details" onClick={() => setSelected(null)}><X size={19} /></button></div><h2 id="session-dialog-title">{selected.title}</h2><p>{dayLabel(dateKey(selected.starts_at, timezone))} · {clock(selected.starts_at, timezone)}–{clock(selected.ends_at, timezone)}</p><p className="muted">{hours(duration(selected))} · {selected.locked ? "Protected from rescheduling" : "Flexible session"}</p>{selected.task_id && selected.status === "planned" && <><label>Actual minutes (for completion)<input id="actual-minutes" type="number" min={0} max={duration(selected)} defaultValue={duration(selected)} /></label><div className="session-actions"><button className="button primary" disabled={busy} onClick={() => mutate(async () => { const input = document.getElementById("actual-minutes") as HTMLInputElement; await api(`/sessions/${selected.id}`, "PATCH", { status: "completed", actual_minutes: Number(input.value) }); setSelected(null); }, "Session completed. Remaining work is ready to plan.")}><Check size={16} />Complete</button>{(["skipped", "missed"] as const).map(status => <button key={status} className="button secondary" disabled={busy} onClick={() => mutate(async () => { await api(`/sessions/${selected.id}`, "PATCH", { status }); setSelected(null); }, "Session status saved. Open Calendar to update the remaining work.")}>Mark {status}</button>)}</div><button className="text-link" disabled={busy} onClick={() => mutate(async () => { const updated = await api<Session>(`/sessions/${selected.id}`, "PATCH", { locked: !selected.locked }); setSelected(updated); }, selected.locked ? "Session unlocked." : "Session protected.")}><LockKeyhole size={15} />{selected.locked ? "Unlock session" : "Keep this time fixed"}</button></>}</section></div>}
  </div>;
}
