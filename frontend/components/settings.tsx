"use client";
import { useState } from "react";
import { Plus, Trash2, Pencil, Radio, ShieldCheck } from "lucide-react";
import type { Preferences, Obligation, SystemStatus } from "../lib/types";
import { api } from "../lib/api";
import { clock } from "../lib/time";
const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export default function Settings({ preferences, obligations, system, refresh, mutate }: {
  preferences: Preferences; obligations: Obligation[]; system: SystemStatus; refresh: () => Promise<void>;
  mutate: (action: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState<Obligation | null | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function savePreferences(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    const data = new FormData(event.currentTarget);
    const updated = { ...preferences } as Record<string, unknown>;
    for (const key of Object.keys(preferences)) {
      updated[key] = key === "monitoring_enabled" ? data.get(key) === "on" : typeof preferences[key as keyof Preferences] === "number" ? Number(data.get(key)) : String(data.get(key));
    }
    try { await api("/preferences", "PUT", updated); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save settings"); }
    finally { setSaving(false); }
  }
  async function saveObligation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    const data = new FormData(event.currentTarget);
    const values = { title: data.get("title"), weekdays: data.getAll("weekdays").map(Number),
      start_time: data.get("start"), end_time: data.get("end"), start_date: data.get("start_date") || null, end_date: data.get("end_date") || null };
    try { await api(editing ? `/obligations/${editing.id}` : "/obligations", editing ? "PUT" : "POST", values); setEditing(undefined); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save obligation"); }
    finally { setSaving(false); }
  }
  return <div className="settings-layout">
    <section className="panel"><div className="panel-heading"><div><h2>Your daily rhythm</h2><p>Hard boundaries keep your schedule realistic.</p></div></div>
      <form className="form-grid" onSubmit={savePreferences}>
        <label className="span-two">Timezone<input name="timezone" aria-label="Timezone" required defaultValue={preferences.timezone} /><small>Use an IANA name, for example America/Los_Angeles.</small></label>
        {([["sleep_start", "Sleep starts"], ["sleep_end", "Wake up"], ["available_start", "Available from"], ["available_end", "Available until"], ["preferred_start", "Prefer work from"], ["preferred_end", "Prefer work until"]] as const).map(([key, label]) =>
          <label key={key}>{label}<input type="time" name={key} required defaultValue={preferences[key]} /></label>)}
        <label>Break after long sessions<select name="break_minutes" defaultValue={preferences.break_minutes}>{[0, 15, 30, 45, 60].map(n => <option key={n} value={n}>{n} minutes</option>)}</select></label><div />
        <details className="span-two"><summary>Scheduling weights</summary><p className="muted">Higher values favor the corresponding preference. Feasibility always comes first.</p><div className="form-grid">
          {([["stability_weight", "Keep existing times"], ["preferred_weight", "Preferred hours"], ["break_weight", "Recovery breaks"], ["context_weight", "Less context switching"], ["spread_weight", "Spread weekly sessions"]] as const).map(([key, label]) =>
            <label key={key}>{label}<input name={key} type="number" min={0} max={100} required defaultValue={preferences[key]} /></label>)}
        </div></details>
        <div className="privacy-card span-two"><ShieldCheck size={22} /><div><strong>Activity is your choice</strong><p>The companion reports application names and idle time. No window titles, screenshots, keys, or browsing history.</p>
          <label className="checkbox-label"><input type="checkbox" name="monitoring_enabled" defaultChecked={preferences.monitoring_enabled} />Enable activity monitoring</label></div></div>
        {error && <p role="alert" className="form-error span-two">{error}</p>}
        <div className="form-actions span-two"><button className="button primary" disabled={saving}>{saving ? "Saving…" : "Save preferences"}</button></div>
      </form>
    </section>
    <div className="stack">
      <section className="panel"><div className="panel-heading"><h2>Connections</h2><Radio size={19} /></div>
        <div className="connection"><span className={`status-dot ${system.ai_mode === "demo" || system.gemini_configured ? "online" : ""}`} /><div><strong>{system.ai_mode === "demo" ? "Deterministic demo" : "Gemini"}</strong><p>{system.ai_mode === "demo" ? "Sample commands available. No API key needed." : system.gemini_configured ? system.gemini_model : "Add GEMINI_API_KEY on the backend."}</p></div></div>
        <div className="connection"><span className={`status-dot ${system.agent_connected ? "online" : ""}`} /><div><strong>Desktop companion</strong><p>{system.agent_connected ? `Connected · ${system.activity_state || "unknown"}` : preferences.monitoring_enabled ? "Waiting for the Windows agent." : "Monitoring disabled."}</p>{system.last_activity_at && <small>Last report {clock(system.last_activity_at, preferences.timezone)}</small>}</div></div>
        <p className="muted">{system.agent_token_configured ? "Agent token configured on backend." : "Set AGENT_TOKEN on the backend and agent to accept reports."}</p>
        <p className="muted">AI mode, model, and keys are configured in the backend .env file. Restart FastAPI after changing them.</p>
      </section>
      <section className="panel"><div className="panel-heading"><div><h2>Fixed obligations</h2><p>Classes, appointments, and other anchors.</p></div><button className="icon-button" aria-label="Add obligation" onClick={() => { setEditing(null); setError(""); }}><Plus size={19} /></button></div>
        {editing !== undefined ? <form className="form-grid" key={editing?.id || "new"} onSubmit={saveObligation}>
          <label className="span-two">Title<input name="title" defaultValue={editing?.title} required maxLength={200} /></label>
          <div className="day-checkboxes span-two">{weekdays.map((day, i) => <label key={day}><input type="checkbox" name="weekdays" value={i} defaultChecked={editing?.weekdays.includes(i)} />{day}</label>)}</div>
          <label>Starts<input type="time" name="start" defaultValue={editing?.start_time || "13:00"} required /></label><label>Ends<input type="time" name="end" defaultValue={editing?.end_time || "15:00"} required /></label>
          <label>From date (optional)<input type="date" name="start_date" defaultValue={editing?.start_date || ""} /></label><label>Through date (optional)<input type="date" name="end_date" defaultValue={editing?.end_date || ""} /></label>
          <div className="form-actions span-two"><button type="button" className="button secondary" onClick={() => setEditing(undefined)}>Cancel</button><button className="button primary" disabled={saving}>Save obligation</button></div>
        </form> : obligations.length ? obligations.map(o => <div className="obligation-row" key={o.id}><div><strong>{o.title}</strong><p>{o.weekdays.map(n => weekdays[n]).join(", ")} · {o.start_time}–{o.end_time}</p></div><button className="icon-button" aria-label={`Edit ${o.title}`} onClick={() => setEditing(o)}><Pencil size={15} /></button><button className="icon-button danger" aria-label={`Delete ${o.title}`} onClick={() => mutate(() => api(`/obligations/${o.id}`, "DELETE"), "Obligation deleted. Generate a new plan to update your calendar.")}><Trash2 size={15} /></button></div>) : <p className="muted">No fixed obligations yet. Add your classes or appointments.</p>}
        <p className="muted">Generate a plan after editing obligations or daily boundaries.</p>
      </section>
    </div>
  </div>;
}
