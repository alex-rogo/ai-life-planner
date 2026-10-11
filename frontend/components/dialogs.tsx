"use client";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../lib/api";
import { dateKey, hours as span, zonedISO } from "../lib/time";
import type { CalendarSource, Category, EventKind, Goal, Obligation, Preferences, Provider, SystemStatus, Task } from "../lib/types";

function Modal({ title, onClose, onSubmit, children, wide }: { title: string; onClose: () => void; onSubmit: (e: FormEvent) => void; children: ReactNode; wide?: boolean }) {
  const box = useRef<HTMLFormElement>(null);
  useEffect(() => {
    box.current?.querySelector<HTMLElement>("input, select")?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <form ref={box} className={`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} onSubmit={e => { e.preventDefault(); onSubmit(e); }}>
        <h2>{title}</h2>
        {children}
      </form>
    </div>
  );
}
function useSubmit(onSaved: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (work: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await work(); onSaved(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return { busy, error, submit };
}
const weekday = (day: string) => (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
const KINDS: { value: EventKind; label: string }[] = [
  { value: "appointment", label: "Appointment" }, { value: "interview", label: "Interview" },
  { value: "personal", label: "Personal" }, { value: "commitment", label: "Fixed commitment (class, meeting)" },
];
const CATEGORIES: { value: Category; label: string }[] = [
  { value: "focus", label: "Focus work" }, { value: "routine", label: "Routine" }, { value: "personal", label: "Personal goal" }, { value: "errand", label: "Errand" },
];
const ESTIMATES = [30, 60, 90, 120, 180, 240, 360, 480, 600];

export function EventDialog({ timezone, today, obligation, onClose, onSaved }: { timezone: string; today: string; obligation?: Obligation; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(obligation?.title ?? "");
  const [kind, setKind] = useState<EventKind>(obligation?.kind ?? "appointment");
  const [date, setDate] = useState(obligation?.start_date ?? today);
  const [start, setStart] = useState(obligation?.start_time ?? "09:00");
  const [end, setEnd] = useState(obligation?.end_time ?? "10:00");
  const [weekly, setWeekly] = useState(obligation ? obligation.end_date === null : false);
  const { busy, error, submit } = useSubmit(onSaved);
  const save = () => submit(() => {
    const body = { title, kind, start_time: start, end_time: end, weekdays: [weekday(date)], start_date: date, end_date: weekly ? null : date };
    return obligation ? api(`/obligations/${obligation.id}`, "PUT", body) : api("/obligations", "POST", body);
  });
  return (
    <Modal title={obligation ? "Edit event" : "Add something important"} onClose={onClose} onSubmit={() => void save()}>
      <label>What is it?<input className="field" required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} placeholder="Dentist cleaning" /></label>
      <label>Type<select className="field" value={kind} onChange={e => setKind(e.target.value as EventKind)}>{KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}</select></label>
      <label>Date<input className="field" type="date" required value={date} onChange={e => setDate(e.target.value)} /></label>
      <div className="row">
        <label>Starts<input className="field" type="time" required step={900} value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>Ends<input className="field" type="time" required step={900} value={end} onChange={e => setEnd(e.target.value)} /></label>
      </div>
      <label className="check"><input type="checkbox" checked={weekly} onChange={e => setWeekly(e.target.checked)} />Repeats every week on this day</label>
      <span className="hint">Times are in {timezone}. Tomo plans flexible work around this and replans your week when you save.</span>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="actions">
        {obligation && <button type="button" className="danger" disabled={busy} onClick={() => void submit(() => api(`/obligations/${obligation.id}`, "DELETE"))}>Delete</button>}
        <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

export function GoalDialog({ timezone, goalId, onClose, onSaved }: { timezone: string; goalId?: string; onClose: () => void; onSaved: () => void }) {
  const [goal, setGoal] = useState<Goal | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [step, setStep] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [category, setCategory] = useState<Category>("focus");
  const { busy, error, submit } = useSubmit(onSaved);
  useEffect(() => {
    if (!goalId) return;
    void Promise.all([api<Goal[]>("/goals"), api<Task[]>("/tasks")]).then(([goals, all]) => {
      const found = goals.find(g => g.id === goalId) ?? null;
      setGoal(found); setTitle(found?.title ?? ""); setDue(found?.deadline ? dateKey(found.deadline, timezone) : "");
      setTasks(all.filter(t => t.goal_id === goalId && t.status !== "cancelled"));
    });
  }, [goalId, timezone]);
  const deadline = due ? zonedISO(due, "23:45", timezone) : null;
  const save = () => submit(async () => {
    const body = { title, description: goal?.description ?? "", deadline };
    const saved = goal ? await api<Goal>(`/goals/${goal.id}`, "PUT", body) : await api<Goal>("/goals", "POST", body);
    if (step.trim()) await api("/tasks", "POST", { title: step.trim(), goal_id: saved.id, duration_minutes: minutes, category, deadline });
  });
  const remove = async (task: Task) => { await api(`/tasks/${task.id}`, "DELETE"); setTasks(list => list.filter(t => t.id !== task.id)); };
  const removeGoal = () => submit(async () => {
    for (const task of tasks) await api(`/tasks/${task.id}`, "DELETE");
    await api(`/goals/${goal!.id}`, "DELETE");
  });
  return (
    <Modal title={goalId ? "Edit goal" : "Add a goal"} onClose={onClose} onSubmit={() => void save()}>
      <label>Goal<input className="field" required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} placeholder="Launch portfolio site" /></label>
      <label>Due date <span className="hint">Optional</span><input className="field" type="date" value={due} onChange={e => setDue(e.target.value)} /></label>
      {goalId && (
        <div>
          <span style={{ fontSize: 13, fontWeight: 600 }}>Steps</span>
          {tasks.map(t => (
            <div key={t.id} className="task-line">
              <span>{t.title}</span>
              <span className="meta">{t.status === "completed" ? "Done" : `${span(Math.max(0, t.duration_minutes - t.completed_minutes))} left`}</span>
              <button type="button" className="x" aria-label={`Remove ${t.title}`} onClick={() => void remove(t)}>×</button>
            </div>
          ))}
          {!tasks.length && <p className="empty">No steps yet.</p>}
        </div>
      )}
      <label>{goalId ? "Add a step" : "First step"} <span className="hint">Optional — Tomo schedules it right away</span>
        <input className="field" maxLength={200} value={step} onChange={e => setStep(e.target.value)} placeholder="Draft the case study" />
      </label>
      <div className="row">
        <label>Estimate<select className="field" value={minutes} onChange={e => setMinutes(Number(e.target.value))}>{ESTIMATES.map(m => <option key={m} value={m}>{span(m)}</option>)}</select></label>
        <label>Kind of work<select className="field" value={category} onChange={e => setCategory(e.target.value as Category)}>{CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}</select></label>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="actions">
        {goal && <button type="button" className="danger" disabled={busy} onClick={() => void removeGoal()}>Delete</button>}
        <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

const PROVIDERS: { value: Exclude<Provider, "demo">; label: string; help: string; example: string }[] = [
  { value: "canvas", label: "Canvas", help: "In Canvas, open Calendar, click “Calendar Feed” at the bottom right, and copy the link.", example: "https://yourschool.instructure.com/feeds/calendars/user_….ics" },
  { value: "google", label: "Google Calendar", help: "In Google Calendar on the web: Settings → your calendar → Integrate calendar → copy “Secret address in iCal format”.", example: "https://calendar.google.com/calendar/ical/…/private-…/basic.ics" },
  { value: "outlook", label: "Outlook", help: "In Outlook on the web: Settings → Calendar → Shared calendars → Publish a calendar → copy the ICS link.", example: "https://outlook.office365.com/owa/calendar/…/calendar.ics" },
  { value: "apple", label: "Apple iCloud", help: "In the Calendar app, share the calendar as a Public Calendar and copy its webcal:// link.", example: "webcal://p01-caldav.icloud.com/published/2/…" },
  { value: "other", label: "Other (.ics link)", help: "Any calendar subscription link ending in .ics, or a webcal:// link.", example: "https://example.com/calendar.ics" },
];

function ago(stamp: string | null, now: string | undefined): string {
  if (!stamp || !now) return "not synced yet";
  const minutes = Math.max(0, Math.round((new Date(now).getTime() - new Date(stamp).getTime()) / 60000));
  return minutes < 1 ? "synced just now" : minutes < 60 ? `synced ${minutes} min ago` : `synced ${Math.round(minutes / 60)} h ago`;
}

/** Connected calendar feeds: imported events are fixed blocks; assignments are due markers. */
export function CalendarConnections({ demo, now, onChanged }: { demo: boolean; now?: string; onChanged: () => void | Promise<void> }) {
  const [list, setList] = useState<CalendarSource[] | null>(null);
  const [provider, setProvider] = useState<Exclude<Provider, "demo">>("canvas");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [working, setWorking] = useState("");
  const [confirming, setConfirming] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api<CalendarSource[]>("/calendars").then(l => { if (live) setList(l); }).catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, []);
  const act = async (key: string, work: () => Promise<unknown>) => {
    setWorking(key); setError(""); setConfirming("");
    try { await work(); setList(await api<CalendarSource[]>("/calendars")); await onChanged(); } catch (e) { setError((e as Error).message); } finally { setWorking(""); }
  };
  const add = () => {
    if (!url.trim() || working) return;
    void act("add", async () => { await api("/calendars", "POST", { provider, name, url }); setUrl(""); setName(""); });
  };
  const choice = PROVIDERS.find(p => p.value === provider)!;
  return (
    <section className="connections" aria-label="Connected calendars">
      <h3>Connected calendars</h3>
      <p className="hint">Events come in as fixed blocks that Tomo plans around but never moves; assignments become due-date markers. Feed links stay on this computer.</p>
      {list?.map(c => (
        <div key={c.id} className="connection">
          <span className={`provider-badge ${c.provider}`} aria-hidden="true">{c.provider === "demo" ? "C" : c.name[0]}</span>
          <div className="stack">
            <span className="title-sm">{c.name}</span>
            {c.last_error
              ? <span className="sync-error">{c.last_error}</span>
              : <span className="meta">{c.events} events · {c.deadlines} assignments{c.all_day ? ` · ${c.all_day} all-day` : ""} · {ago(c.last_synced_at, now)}</span>}
            <span className="meta mono">{c.url_hint}</span>
          </div>
          <button type="button" className="ghost" disabled={!!working} onClick={() => void act(c.id, () => api(`/calendars/${c.id}/sync`, "POST"))}>{working === c.id ? "Syncing…" : "Sync now"}</button>
          {confirming === c.id
            ? <button type="button" className="danger small" disabled={!!working} onClick={() => void act(`remove-${c.id}`, () => api(`/calendars/${c.id}`, "DELETE"))}>Remove</button>
            : <button type="button" className="x" aria-label={`Remove ${c.name}`} onClick={() => setConfirming(c.id)}>×</button>}
        </div>
      ))}
      {list && !list.length && <p className="empty">No calendars connected yet.</p>}
      <div className="connect">
        <div className="row">
          <label>Calendar<select className="field" value={provider} onChange={e => setProvider(e.target.value as Exclude<Provider, "demo">)}>{PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}</select></label>
          <label>Name <span className="hint">Optional</span><input className="field" maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder={choice.label} /></label>
        </div>
        <span className="hint">{choice.help}</span>
        <label>Feed link
          <input className="field" value={url} onChange={e => setUrl(e.target.value)} placeholder={choice.example} autoComplete="off" spellCheck={false}
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        </label>
        <div className="actions">
          {demo && <button type="button" className="secondary" disabled={!!working} onClick={() => void act("demo", () => api("/calendars", "POST", { provider: "demo", url: "demo://canvas" }))}>{working === "demo" ? "Adding…" : "Try the demo Canvas feed"}</button>}
          <button type="button" className="primary" disabled={!url.trim() || !!working} onClick={add}>{working === "add" ? "Connecting…" : "Connect"}</button>
        </div>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
    </section>
  );
}

export function SettingsDialog({ preferences, system, onClose, onSaved, onCalendarsChanged }: { preferences: Preferences; system: SystemStatus | null; onClose: () => void; onSaved: () => void; onCalendarsChanged: () => void | Promise<void> }) {
  const [form, setForm] = useState(preferences);
  const { busy, error, submit } = useSubmit(onSaved);
  const set = <K extends keyof Preferences>(key: K, value: Preferences[K]) => setForm(f => ({ ...f, [key]: value }));
  const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  const clock = (key: keyof Preferences, label: string) => (
    <label>{label}<input className="field" type="time" step={900} required value={form[key] as string} onChange={e => set(key, e.target.value as never)} /></label>
  );
  const companion = !system?.agent_token_configured ? "Set AGENT_TOKEN on the backend to allow the Windows companion."
    : system.agent_connected ? "Companion connected." : "Companion not connected. Start it with --enable.";
  return (
    <Modal title="Settings" wide onClose={onClose} onSubmit={() => void submit(() => api("/preferences", "PUT", form))}>
      <label>Timezone<input className="field" list="tomo-zones" required value={form.timezone} onChange={e => set("timezone", e.target.value)} /></label>
      <datalist id="tomo-zones">{zones.map(z => <option key={z} value={z} />)}</datalist>
      <div className="row">{clock("available_start", "Day starts")}{clock("available_end", "Day ends")}</div>
      <div className="row">{clock("preferred_start", "Best focus from")}{clock("preferred_end", "Best focus until")}</div>
      <div className="row">{clock("sleep_start", "Sleep from")}{clock("sleep_end", "Wake at")}</div>
      <label>Break between long blocks
        <select className="field" value={form.break_minutes} onChange={e => set("break_minutes", Number(e.target.value))}>{[0, 15, 30, 45, 60].map(m => <option key={m} value={m}>{m ? `${m} min` : "None"}</option>)}</select>
      </label>
      <label className="check"><input type="checkbox" checked={form.monitoring_enabled} onChange={e => set("monitoring_enabled", e.target.checked)} />Enable activity monitoring</label>
      <span className="hint">The optional Windows companion reports the foreground app and idle time so Tomo can suggest replanning. {companion}</span>
      <CalendarConnections demo={!!system && (system.ai_mode === "demo" || system.demo_clock)} now={system?.now} onChanged={onCalendarsChanged} />
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
