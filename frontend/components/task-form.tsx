"use client";
import { useState } from "react";
import type { Goal, Task } from "../lib/types";
import { dateKey, zonedISO } from "../lib/time";
export default function TaskForm({ task, goals, timezone, onSave, onCancel }: {
  task?: Task; goals: Goal[]; timezone: string; onSave: (values: object) => Promise<void>; onCancel: () => void;
}) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      await onSave({
        title: form.get("title"), description: form.get("description"), goal_id: form.get("goal_id") || null,
        duration_minutes: Number(form.get("duration")), priority: Number(form.get("priority")),
        min_session_minutes: Number(form.get("min")), max_session_minutes: Number(form.get("max")),
        recurrence: form.get("recurrence"), sessions_per_week: Number(form.get("frequency")),
        deadline: form.get("deadline") ? zonedISO(String(form.get("deadline")), "23:59", timezone) : null,
        activity_apps: String(form.get("apps")).split(",").map(s => s.trim()).filter(Boolean),
      });
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save task"); }
    finally { setSaving(false); }
  }
  return <form onSubmit={submit} className="form-grid">
    <label className="span-two">Task name<input name="title" required maxLength={200} defaultValue={task?.title} placeholder="What needs your attention?" autoFocus /></label>
    <label className="span-two">Notes<textarea name="description" defaultValue={task?.description} maxLength={4000} rows={2} /></label>
    <label>Estimated minutes<input name="duration" type="number" min={15} max={10080} step={15} required defaultValue={task?.duration_minutes || 60} /></label>
    <label>Priority<select name="priority" defaultValue={task?.priority || 3}>{[1, 2, 3, 4, 5].map(p => <option key={p} value={p}>{p} · {["Low", "Light", "Normal", "High", "Urgent"][p - 1]}</option>)}</select></label>
    <label>Minimum session<input name="min" type="number" min={15} max={10080} step={15} required defaultValue={task?.min_session_minutes || 30} /></label>
    <label>Maximum session<input name="max" type="number" min={15} max={10080} step={15} required defaultValue={task?.max_session_minutes || 90} /></label>
    <label>Repeat<select name="recurrence" defaultValue={task?.recurrence || "none"}><option value="none">One-time work</option><option value="daily">Every day</option><option value="weekly">Times per week</option></select></label>
    <label>Sessions per week<input name="frequency" type="number" min={1} max={7} defaultValue={task?.sessions_per_week || 3} /></label>
    <label>Deadline ({timezone})<input name="deadline" type="date" defaultValue={task?.deadline ? dateKey(task.deadline, timezone) : ""} /></label>
    <label>Goal<select name="goal_id" defaultValue={task?.goal_id || ""}><option value="">Independent task</option>{goals.map(g => <option key={g.id} value={g.id}>{g.title}</option>)}</select></label>
    <label className="span-two">Associated apps (optional)<input name="apps" defaultValue={task?.activity_apps.join(", ")} placeholder="Code.exe, devenv.exe" /><small>Weak evidence only. App activity never completes a task.</small></label>
    {error && <p role="alert" className="form-error span-two">{error}</p>}
    <div className="form-actions span-two"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary" disabled={saving}>{saving ? "Saving…" : task ? "Save changes" : "Create task"}</button></div>
  </form>;
}
