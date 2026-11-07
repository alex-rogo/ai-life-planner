"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api } from "../lib/api";
import { addDays, dateKey, dayLabel, minutesOfDay, zonedISO } from "../lib/time";
import { isoWeek, matchKeys, rangeFor, shift, withPreview } from "../lib/calendar";
import type { ChatResult, Decision, Message, Obligation, Overview, Preferences, Proposal, Session, Suggestion, SystemStatus, Upcoming, View } from "../lib/types";
import Assistant from "./assistant";
import { EventDialog, GoalDialog, SettingsDialog } from "./dialogs";
import { DayView, MonthView, WeekView } from "./schedule";
import Sidebar from "./sidebar";
import ThemeToggle from "./theme-toggle";

const PATHS: Record<View, string> = { day: "/app", week: "/app/week", month: "/app/month" };
const STEP_LABEL: Record<View, [string, string, string]> = {
  day: ["Previous day", "Today", "Next day"], week: ["Previous week", "This week", "Next week"], month: ["Previous month", "This month", "Next month"],
};
const VIEWS: View[] = ["day", "week", "month"];
interface RangeData { overview: Overview; sessions: Session[]; }
interface ChatData { messages: Message[]; proposal: Proposal | null; suggestions: Suggestion[]; }

const rangeKey = (view: View, day: string) => `${view}:${rangeFor(view, day).start}`;
async function fetchRange(view: View, day: string, timezone: string): Promise<[string, RangeData]> {
  const { start, days } = rangeFor(view, day);
  // Overview first: it settles elapsed work and tops up the plan before sessions are read.
  const overview = await api<Overview>(`/overview?start=${start}&days=${days}`);
  const from = encodeURIComponent(zonedISO(start, "00:00", timezone));
  const to = encodeURIComponent(zonedISO(addDays(start, days), "00:00", timezone));
  return [rangeKey(view, day), { overview, sessions: await api<Session[]>(`/sessions?start=${from}&end=${to}`) }];
}
async function fetchChat(): Promise<ChatData> {
  const [messages, proposal, suggestions] = await Promise.all([
    api<Message[]>("/messages"), api<Proposal | null>("/proposals/current"), api<Suggestion[]>("/suggestions"),
  ]);
  return { messages, proposal, suggestions };
}
/**
 * What the calendar shows and how it got there. `keys` gives every session a stable visual
 * identity carried across changes; `before` is what was on screen before the latest change, so
 * the views can play the change as a show. It is cleared once any show has finished.
 */
export interface Stage {
  id: number; range: string; signature: string; sessions: Session[]; keys: Record<string, string>;
  before: { sessions: Session[]; keys: Record<string, string> } | null;
}
const signatureOf = (list: Session[]) => list.map(s => `${s.id}|${s.starts_at}|${s.ends_at}|${s.status}|${s.locked}|${s.change ?? ""}`).join(",");
const identity = (list: Session[]) => Object.fromEntries(list.map(s => [s.id, s.id]));
const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Any change to the sessions of the range on screen plays as a show, chained from exactly what is
 * displayed (even mid-show), so nothing is ever recreated in a new place. Showing a different
 * range (navigation or first load) swaps in without animation.
 */
function useStage(sessions: Session[], range: string): Stage {
  const signature = signatureOf(sessions);
  const [stage, setStage] = useState<Stage>(() => ({ id: 0, range, signature, sessions, keys: identity(sessions), before: null }));
  if (stage.range !== range || stage.signature !== signature) {
    // Adjusting state while rendering (not in an effect) means no frame ever shows new data
    // under old identities.
    const animate = stage.range === range && !prefersReducedMotion();
    setStage({
      id: stage.id + 1, range, signature, sessions,
      keys: animate ? matchKeys(stage.sessions, stage.keys, sessions) : identity(sessions),
      before: animate ? { sessions: stage.sessions, keys: stage.keys } : null,
    });
  }
  useEffect(() => {
    if (!stage.before) return;
    const id = stage.id;
    const done = setTimeout(() => setStage(s => (s.id === id ? { ...s, before: null } : s)), 12000);
    return () => clearTimeout(done);
  }, [stage.id, stage.before]);
  return stage;
}
type Dialog = { type: "event"; obligation?: Obligation } | { type: "goal"; goalId?: string } | { type: "settings" } | null;

/** Mounted once by the (planner) layout, so switching Day/Week/Month keeps state and cached data. */
export default function Planner({ mode = "demo", onExit }: { mode?: "demo" | "account"; onExit?: () => void }) {
  const router = useRouter();
  const params = useSearchParams();
  const pathname = usePathname();
  const view: View = pathname.startsWith("/app/week") ? "week" : pathname.startsWith("/app/month") ? "month" : "day";
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [ranges, setRanges] = useState<Record<string, RangeData>>({});
  const [shownKey, setShownKey] = useState("");
  const [chat, setChat] = useState<ChatData | null>(null);
  const [generation, setGeneration] = useState(0);
  const [asking, setAsking] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [chatOpen, setChatOpen] = useState(true);
  const [dialog, setDialog] = useState<Dialog>(null);
  // The server's clock is the source of truth (it may be a demo clock), so keep the difference.
  const [tick, setTick] = useState(() => Date.now());
  const [skew, setSkew] = useState(0);
  const now = new Date(tick + skew);
  const inputRef = useRef<HTMLInputElement>(null);

  const timezone = prefs?.timezone ?? "";
  const today = timezone ? dateKey(now, timezone) : "";
  const requested = params.get("date");
  const day = requested && /^\d{4}-\d{2}-\d{2}$/.test(requested) ? requested : today;
  const range = day ? rangeFor(view, day) : null;
  const start = range?.start ?? "";

  useEffect(() => {
    let live = true;
    Promise.all([api<Preferences>("/preferences"), api<SystemStatus>("/system")])
      .then(([p, s]) => { if (live) { setPrefs(p); setSystem(s); setSkew(new Date(s.now).getTime() - Date.now()); } })
      .catch((e: Error) => { if (live) setLoadError(e.message); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!timezone || !day) return;
    let live = true;
    // Refresh the visible range first (cached data stays on screen meanwhile), then prefetch the
    // other views for this date so switching between them is instant.
    (async () => {
      for (const v of [view, ...VIEWS.filter(x => x !== view)]) {
        const [key, data] = await fetchRange(v, day, timezone);
        if (!live) return;
        setRanges(all => ({ ...all, [key]: data }));
        if (v === view) {
          setShownKey(key); setLoadError("");
          const messages = await fetchChat();
          if (!live) return;
          setChat(messages);
        }
      }
    })().catch((e: Error) => { if (live) setLoadError(e.message); });
    return () => { live = false; };
  }, [view, day, timezone, generation]);
  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), 60000);
    return () => clearInterval(timer);
  }, []);
  // An open page keeps imported calendars current: every few minutes, refetch (the backend
  // re-imports feeds older than 15 minutes) and refresh the sync status.
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      setGeneration(g => g + 1);
      api<SystemStatus>("/system").then(setSystem).catch(() => {});
    }, 5 * 60000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (event.key !== "/" || event.metaKey || event.ctrlKey || target?.closest("input, textarea, select, [contenteditable], [role=dialog]")) return;
      event.preventDefault(); setChatOpen(true); setTimeout(() => inputRef.current?.focus(), 0);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // After a change every cached range may be stale: show the fresh visible range, drop the rest,
  // and let the effect prefetch the other views again.
  const refresh = async () => {
    const [[key, data], messages] = await Promise.all([fetchRange(view, day, timezone), fetchChat()]);
    setRanges({ [key]: data }); setShownKey(key); setChat(messages); setGeneration(g => g + 1);
  };
  const run = async (work: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await work(); } catch (e) { setError((e as Error).message); }
    try { await refresh(); } catch (e) { setLoadError((e as Error).message); }
    setBusy(false); setAsking("");
  };
  const send = (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    setAsking(message);
    void run(() => api<ChatResult>("/assistant", "POST", { message, plan: { days: 7 } }, 300000));
  };
  // Demo-only chips: empty the calendar, or reload the sample week with the demo Canvas feed.
  const sampleData = async (action: "clear" | "populate") => {
    await api(`/demo/${action}`, "POST");
    setSystem(await api<SystemStatus>("/system"));
  };
  const tools = system?.sample_data_tools ? [
    { label: "Load sample data", run: () => void run(() => sampleData("populate")) },
    { label: "Clear the calendar", confirm: "Click again to clear everything", run: () => void run(() => sampleData("clear")) },
  ] : [];
  const check = (item: Upcoming, done: boolean) => void run(() => api(`/checklist/${encodeURIComponent(item.key)}`, "PUT", { done }));
  const decide = (id: string, action: "apply" | "discard" | "undo") => void run(() => api<Decision>(`/proposals/${id}/${action}`, "POST"));
  const answer = (id: string, decision: "confirm" | "dismiss") => void run(() => api(`/suggestions/${id}/decision`, "POST", { decision }));
  const href = (to: View, target: string) => target && target !== today ? `${PATHS[to]}?date=${target}` : PATHS[to];
  const go = (target: string, to: View = view) => router.push(href(to, target), { scroll: false });
  const openItem = async (item: Upcoming) => {
    if (item.goal_id) setDialog({ type: "goal", goalId: item.goal_id });
    if (item.obligation_id) {
      const all = await api<Obligation[]>("/obligations");
      const match = all.find(o => o.id === item.obligation_id);
      if (match) setDialog({ type: "event", obligation: match });
    }
  };
  // Calendar connections change both the system status and the calendar, but keep Settings open.
  const reloadAll = async () => {
    setSystem(await api<SystemStatus>("/system"));
    await refresh();
  };
  const saved = async () => {
    setDialog(null);
    const [p, s] = await Promise.all([api<Preferences>("/preferences"), api<SystemStatus>("/system")]);
    setPrefs(p); setSystem(s);
    if (p.timezone === timezone) await refresh();
  };
  // Until the requested range arrives, keep showing the previous one rather than a blank screen.
  const requestedRange = day ? rangeKey(view, day) : "";
  const displayed = ranges[requestedRange] ? requestedRange : shownKey;
  const shown = ranges[displayed];
  const overview = shown?.overview ?? null, sessions = shown?.sessions ?? [];
  const { messages = [], proposal = null, suggestions = [] } = chat ?? {};

  const pending = proposal?.status === "pending" ? proposal : null;
  const stage = useStage(withPreview(sessions, pending?.preview), displayed);
  const hour = timezone ? Math.floor(minutesOfDay(now.toISOString(), timezone) / 60) : 9;
  const weekday = day ? dayLabel(day, { weekday: "long" }).toUpperCase() : "";
  const kicker = !day ? "" : view === "day"
    ? (day === today ? `${weekday} · ${now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: timezone || undefined })}` : weekday)
    : view === "week" ? `Week ${isoWeek(start)}${today >= start && today < addDays(start, 7) ? ` · today is ${dayLabel(today, { weekday: "long" })}` : ""}`
    : day.slice(0, 4);
  const headline = view === "month" && day ? dayLabel(`${day.slice(0, 7)}-15`, { month: "long", year: "numeric" }) : overview?.headline ?? "";
  const briefLabel = view === "week" ? "Week brief." : view === "month" ? "Month brief." : day !== today ? "Day brief."
    : hour < 12 ? "Morning brief." : hour < 17 ? "Afternoon brief." : "Evening brief.";
  const [prev, current, next] = STEP_LABEL[view];
  // "Synced with Canvas · 2 min ago", as in the design, once calendars are connected.
  const calendars = system?.calendars ?? [];
  const lastSync = calendars.map(c => c.last_synced_at).filter((x): x is string => !!x).sort().at(-1);
  const minutesAgo = lastSync ? Math.max(0, Math.round((now.getTime() - new Date(lastSync).getTime()) / 60000)) : null;
  // A calendar that failed to sync is shown loudly: its deadlines may be out of date.
  const failing = calendars.filter(c => c.error);
  const age = (stamp: string | null) => {
    if (!stamp) return "nothing has been imported yet";
    const minutes = Math.max(0, Math.round((now.getTime() - new Date(stamp).getTime()) / 60000));
    return `what you see was imported ${minutes < 60 ? `${minutes} min` : minutes < 2880 ? `${Math.round(minutes / 60)} h` : `${Math.round(minutes / 1440)} days`} ago`;
  };
  const synced = !calendars.length ? "" : failing.length ? " · Calendar sync issue"
    : ` · Synced with ${calendars.length === 1 ? calendars[0].name : `${calendars.length} calendars`}${minutesAgo === null ? "" : minutesAgo < 1 ? " · just now" : ` · ${minutesAgo} min ago`}`;
  const status = system ? `Tomo · ${{ gemini: "Gemini", deepseek: "DeepSeek", demo: "Demo assistant" }[system.ai_mode]}${system.demo_clock ? " · Demo clock" : ""}${synced}${prefs?.monitoring_enabled ? " · Activity on" : ""}` : "";

  return (
    <div className="tomo">
      <header className="topbar">
        <div className="brand">Tomo</div>
        <div className="nav-steps">
          <button className="btn btn-square" aria-label={prev} onClick={() => day && go(shift(view, day, -1))}>‹</button>
          <button className="btn btn-today" onClick={() => router.push(PATHS[view], { scroll: false })}>{current}</button>
          <button className="btn btn-square" aria-label={next} onClick={() => day && go(shift(view, day, 1))}>›</button>
        </div>
        <nav role="tablist" aria-label="View" className="tabs">
          {(["day", "week", "month"] as const).map(v => (
            <Link key={v} role="tab" aria-selected={v === view} className="tab" scroll={false} href={href(v, day)}>{v[0].toUpperCase() + v.slice(1)}</Link>
          ))}
        </nav>
        <div className="spacer" />
        <span className="status-line">{status}</span>
        <ThemeToggle />
        {onExit && <button className="exit-link" onClick={onExit}>{mode === "demo" ? "Leave demo" : "Sign out"}</button>}
        <button className="avatar" aria-label="Profile and settings" onClick={() => setDialog({ type: "settings" })}>
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></svg>
        </button>
      </header>
      {failing.map(c => (
        <div key={c.name} className="sync-warning" role="alert">
          <strong>{c.name} couldn’t sync, so {age(c.last_success_at)}.</strong> {c.error}{" "}
          <button className="link-btn" onClick={() => setDialog({ type: "settings" })}>Open calendar settings</button>
        </div>
      ))}

      {!overview && !loadError ? (
        <div className="columns"><div className="card panel center" role="status"><h2>Opening your planner…</h2><p className="meta">The first visit can take a little longer. Your calendar will appear here.</p></div></div>
      ) : loadError && !overview ? (
        <div className="columns"><div className="card panel center"><h2>Can’t reach your planner</h2><p className="meta">{loadError}</p><button className="ghost" onClick={() => window.location.reload()}>Try again</button></div></div>
      ) : (
        <div className="columns">
          <Sidebar view={view} overview={overview} today={today} busy={busy} onCheck={check} onAddEvent={() => setDialog({ type: "event" })} onAddGoal={() => setDialog({ type: "goal" })}
            onOpenGoal={id => setDialog({ type: "goal", goalId: id })} onOpenItem={item => void openItem(item)} />
          <main className={`center ${view}`}>
            <div className="intro">
              <div>
                <div className="kicker">{kicker}</div>
                <h1 className="headline">{headline}</h1>
              </div>
              {view !== "month" && (
                <div className="stats">{overview?.stats.map(s => <div key={s.label} className="stat"><span>{s.label}</span><span>{s.value}</span></div>)}</div>
              )}
            </div>
            {mode === "account" && overview && overview.goals.length === 0 && stage.sessions.length === 0 && (
              <div className="card panel first-plan">
                <span className="entry-eyebrow">YOUR FIRST PLAN</span>
                <h2>Start with one thing that matters.</h2>
                <p>Add a goal, then give it a task. Tomo will find time for it around your commitments.</p>
                <button className="primary" onClick={() => setDialog({ type: "goal" })}>Add your first goal</button>
              </div>
            )}
            {overview && timezone && (view === "day"
              ? <DayView day={day} today={today} timezone={timezone} sessions={stage.sessions} overview={overview} now={now} previewing={!!pending} stage={stage} />
              : view === "week"
              ? <WeekView start={start} today={today} timezone={timezone} sessions={stage.sessions} overview={overview} now={now} previewing={!!pending} stage={stage} onOpenDay={d => go(d, "day")} />
              : <MonthView start={start} month={day.slice(0, 7)} today={today} timezone={timezone} sessions={stage.sessions} overview={overview} onOpenDay={d => go(d, "day")} />)}
          </main>
          <Assistant view={view} open={chatOpen} onToggle={() => setChatOpen(o => !o)} inputRef={inputRef}
            briefLabel={briefLabel} brief={overview?.brief ?? ""} prompts={overview?.prompts ?? []}
            messages={messages} proposal={proposal} suggestions={suggestions} asking={asking} busy={busy} error={error}
            onSend={send} onDecide={decide} onAnswer={answer} tools={tools} />
        </div>
      )}

      {dialog?.type === "event" && <EventDialog timezone={timezone} today={today} obligation={dialog.obligation} onClose={() => setDialog(null)} onSaved={saved} />}
      {dialog?.type === "goal" && <GoalDialog timezone={timezone} goalId={dialog.goalId} onClose={() => setDialog(null)} onSaved={saved} />}
      {dialog?.type === "settings" && prefs && <SettingsDialog preferences={prefs} system={system} onClose={() => setDialog(null)} onSaved={saved} onCalendarsChanged={reloadAll} />}
    </div>
  );
}
