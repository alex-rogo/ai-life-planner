import { addDays, dateKey, minutesOfDay } from "./time";
import type { Category, Session, UpcomingKind, View } from "./types";

export const CATEGORY: Record<Category | "fixed", { color: string; bg: string; label: string }> = {
  focus: { color: "var(--focus)", bg: "var(--focus-bg)", label: "Focus work" },
  fixed: { color: "var(--fixed)", bg: "var(--fixed-bg)", label: "Fixed commitment" },
  routine: { color: "var(--routine)", bg: "var(--routine-bg)", label: "Routine" },
  personal: { color: "var(--personal)", bg: "var(--personal-bg)", label: "Personal goal" },
  errand: { color: "var(--errand)", bg: "var(--errand-bg)", label: "Errand" },
};
export const LEGEND = (["focus", "fixed", "routine", "personal", "errand"] as const).map(key => ({ key, ...CATEGORY[key] }));
export const KIND: Record<UpcomingKind, { color: string; tint: string }> = {
  Interview: { color: "var(--interview)", tint: "var(--interview-bg)" },
  Appointment: { color: "var(--fixed)", tint: "var(--fixed-bg)" },
  Project: { color: "var(--focus)", tint: "var(--focus-bg)" },
  Personal: { color: "var(--personal)", tint: "var(--personal-bg)" },
  Assignment: { color: "var(--routine)", tint: "var(--routine-bg)" },
};
export const GOAL_COLORS = ["var(--focus)", "var(--fixed)", "var(--personal)", "var(--routine)"];
export const CHANGE_COLORS: Record<string, string> = {
  Moved: "var(--interview)", Removed: "var(--interview)", Shortened: "var(--personal)", Extended: "var(--personal)",
  Added: "var(--focus)", "New goal": "var(--focus)", Kept: "var(--muted)", Updated: "var(--muted)",
};

/** 9:30, 12:05 — the design's compact clock without am/pm. */
export function shortClock(minutes: number): string {
  const h = Math.floor(minutes / 60) % 24, m = minutes % 60;
  return `${((h + 11) % 12) + 1}:${m < 10 ? "0" : ""}${m}`;
}
export function hourLabel(hour: number): string {
  return `${((hour + 11) % 12) + 1} ${hour < 12 || hour === 24 ? "am" : "pm"}`;
}

/** Monday of the week containing day (YYYY-MM-DD). */
export function weekStart(day: string): string {
  const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
  return addDays(day, -((weekday + 6) % 7));
}
export function rangeFor(view: View, day: string): { start: string; days: number } {
  if (view === "day") return { start: day, days: 1 };
  if (view === "week") return { start: weekStart(day), days: 7 };
  return { start: weekStart(`${day.slice(0, 7)}-01`), days: 42 };
}
export function shift(view: View, day: string, direction: number): string {
  if (view === "day") return addDays(day, direction);
  if (view === "week") return addDays(day, 7 * direction);
  const date = new Date(`${day.slice(0, 7)}-01T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + direction);
  return date.toISOString().slice(0, 10);
}
/** ISO week number, as in "WEEK 41". */
export function isoWeek(day: string): number {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 3 - ((date.getUTCDay() + 6) % 7));
  const first = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((date.getTime() - first.getTime()) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7);
}

export interface Block {
  session: Session; top: number; height: number; start: number; end: number;
  done: boolean; proposed: boolean; tag: string; kind: "done" | "proposed" | "due" | "plain";
}
/** Local minutes [start, end) a session occupies on one day, or null if it doesn't touch it. */
export function spanOn(session: Session, day: string, timezone: string): [number, number] | null {
  const startDay = dateKey(session.starts_at, timezone), endDay = dateKey(session.ends_at, timezone);
  if (startDay > day || endDay < day || (endDay === day && startDay < day && minutesOfDay(session.ends_at, timezone) === 0)) return null;
  return [startDay < day ? 0 : minutesOfDay(session.starts_at, timezone), endDay > day ? 1440 : minutesOfDay(session.ends_at, timezone)];
}

/**
 * Vertical time scale with a height per hour row. Hours with nothing booked are compressed so
 * the booked ones get the space; `offsets[i]` is the top of the row for hour `first + i`.
 */
export interface Scale { first: number; last: number; offsets: number[]; busy: boolean[]; total: number; }
export const EMPTY_HOUR = 0.35;
const MIN_EMPTY_ROW = 18;

/** Which hour rows in [first, last) have a session on any of the given days. */
export function busyHours(sessions: Session[], days: string[], timezone: string, first: number, last: number): boolean[] {
  const busy = Array.from({ length: last - first }, () => false);
  for (const session of sessions) {
    if (session.status === "skipped" || session.status === "missed") continue;
    for (const day of days) {
      const span = spanOn(session, day, timezone);
      if (!span) continue;
      for (let h = Math.max(first, Math.floor(span[0] / 60)); h < Math.min(last, Math.ceil(span[1] / 60)); h++) busy[h - first] = true;
    }
  }
  // With nothing booked there is nothing to emphasise; keep the grid even.
  return busy.some(Boolean) ? busy : busy.map(() => true);
}

/** Height of a booked hour so all rows fill `available` px, clamped; `fallback` when not fitting. */
export function fitUnit(busy: boolean[], available: number, min: number, max: number, fallback: number): number {
  if (available <= 0) return fallback;
  const full = busy.filter(Boolean).length, empty = busy.length - full;
  let unit = available / (full + empty * EMPTY_HOUR);
  if (unit * EMPTY_HOUR < MIN_EMPTY_ROW && full) unit = (available - empty * MIN_EMPTY_ROW) / full;
  return Math.min(max, Math.max(min, Math.floor(unit)));
}

export function hourScale(busy: boolean[], first: number, last: number, unit: number): Scale {
  const offsets = [0];
  busy.forEach((b, i) => offsets.push(offsets[i] + (b ? unit : Math.max(MIN_EMPTY_ROW, Math.round(unit * EMPTY_HOUR)))));
  return { first, last, offsets, busy, total: offsets[offsets.length - 1] };
}

/** Pixel offset of a local minute-of-day on the scale. */
export function yAt(scale: Scale, minute: number): number {
  const m = Math.min(Math.max(minute, scale.first * 60), scale.last * 60);
  const i = Math.min(Math.floor(m / 60) - scale.first, scale.offsets.length - 2);
  const row = scale.offsets[i + 1] - scale.offsets[i];
  return Math.round(scale.offsets[i] + ((m - (scale.first + i) * 60) / 60) * row);
}

/** Position a session inside one local day column on the given scale. */
export function layout(sessions: Session[], day: string, timezone: string, scale: Scale, now: Date, previewing: boolean): Block[] {
  const floor = scale.first * 60, ceiling = scale.last * 60;
  return sessions.flatMap(session => {
    const span = spanOn(session, day, timezone);
    if (!span) return [];
    const [start, end] = span;
    const top = Math.max(start, floor), bottom = Math.min(end, ceiling);
    if (bottom <= top) return [];
    const elapsed = new Date(session.ends_at) <= now;
    const done = session.status !== "planned" || elapsed;
    const proposed = previewing && !!session.change;
    const due = !done && !!session.deadline && dateKey(session.deadline, timezone) === day;
    const tag = proposed ? `Proposed · ${session.change}`
      : session.status === "skipped" ? "Skipped" : session.status === "missed" ? "Missed"
      : done ? "Done" : due ? "Due today" : "";
    return [{
      session, start, end, done, proposed, tag,
      top: yAt(scale, top), height: Math.max(12, yAt(scale, bottom) - yAt(scale, top)),
      kind: proposed ? "proposed" : done ? "done" : due ? "due" : "plain",
    }];
  });
}

/** A block placed in a column (the day index in Week view, 0 in Day view) under its visual key. */
export interface Placed extends Block { col: number; key: string; }
export type Phase = "stay" | "shift" | "move" | "enter" | "exit";
/** One block's part in a show. The same `key` means the same element on screen. */
/** `ms` is how long a move or shift takes. */
export interface Cue extends Placed { phase: Phase; delay: number; typeAt: number; ms: number; }
export interface Show { cues: Cue[]; shiftAt: number; duration: number; }

/** Milliseconds for each stage of a calendar change. Removal = strike through the text, then fade. */
export const TIMING = {
  strike: 320, fade: 280, shift: 450, move: 560, moveStagger: 110, moveSpread: 1800,
  draw: 380, drawStagger: 420, drawSpread: 3600, typeLead: 240, perChar: 24,
};
const EXIT = TIMING.strike + TIMING.fade;

const owner = (s: Session) => s.task_id ?? s.obligation_id ?? s.title;

/**
 * Carry visual identity from the sessions on screen to the next set, so an element is never
 * recreated for something that merely changed. The solver gives moved work a new id, so sessions
 * match by id, then the same task at the same times, then the same task nearest in time.
 * Unmatched new sessions get their own id as key.
 */
export function matchKeys(before: Session[], keys: Record<string, string>, after: Session[]): Record<string, string> {
  const left = [...before];
  const take = (match: (b: Session) => boolean) => {
    const i = left.findIndex(match);
    return i < 0 ? null : left.splice(i, 1)[0];
  };
  const pairs = after.map(a => ({ a, b: take(b => b.id === a.id) }));
  for (const p of pairs) if (!p.b) p.b = take(b => owner(b) === owner(p.a) && b.starts_at === p.a.starts_at && b.ends_at === p.a.ends_at);
  for (const p of pairs) {
    if (p.b) continue;
    const distance = (b: Session) => Math.abs(new Date(b.starts_at).getTime() - new Date(p.a.starts_at).getTime());
    const nearest = left.filter(b => owner(b) === owner(p.a)).sort((x, y) => distance(x) - distance(y))[0];
    if (nearest) p.b = take(b => b === nearest);
  }
  return Object.fromEntries(pairs.map(({ a, b }) => [a.id, b ? keys[b.id] ?? b.id : a.id]));
}

const slot = (p: Placed) => `${p.col}:${p.start}:${p.end}`;

/**
 * Stage a change from `before` to `after` (paired by key) like a short show: removed blocks are
 * struck through and fade, blocks displaced only by the hour scale shift together with the hour
 * lines, moved blocks travel one after another, then new blocks are drawn and typed in one at a
 * time. Long batches speed up so the whole show stays within a few seconds.
 */
export function choreograph(before: Placed[], after: Placed[]): Show {
  const old = new Map(before.map(b => [b.key, b]));
  const present = new Set(after.map(a => a.key));
  const exits = before.filter(b => !present.has(b.key));
  const shiftAt = exits.length ? EXIT : 0;
  const shiftMs = TIMING.shift, moveMs = TIMING.move;
  const moveAt = shiftAt + TIMING.shift;
  const cues: Cue[] = exits.map(b => ({ ...b, phase: "exit", delay: 0, typeAt: 0, ms: 0 }));
  const moving: Placed[] = [], entering: Placed[] = [];
  for (const a of after) {
    const b = old.get(a.key);
    if (!b) entering.push(a);
    else if (slot(a) !== slot(b)) moving.push(a);
    else cues.push({ ...a, phase: a.top === b.top && a.height === b.height ? "stay" : "shift", delay: shiftAt, typeAt: 0, ms: shiftMs });
  }
  const moveStagger = Math.min(TIMING.moveStagger, TIMING.moveSpread / Math.max(1, moving.length));
  moving.sort((x, y) => x.col - y.col || x.start - y.start).forEach((a, i) => cues.push({ ...a, phase: "move", delay: moveAt + i * moveStagger, typeAt: 0, ms: moveMs }));
  const movesEnd = moving.length ? moveAt + (moving.length - 1) * moveStagger + moveMs : moveAt;
  const drawStagger = Math.min(TIMING.drawStagger, TIMING.drawSpread / Math.max(1, entering.length));
  let end = movesEnd;
  entering.sort((x, y) => x.col - y.col || x.start - y.start).forEach((a, i) => {
    const delay = movesEnd + i * drawStagger, typeAt = delay + TIMING.typeLead;
    cues.push({ ...a, phase: "enter", delay, typeAt, ms: 0 });
    end = Math.max(end, typeAt + (a.session.title.length + 12) * TIMING.perChar);
  });
  return { cues, shiftAt, duration: end + 200 };
}

/** While a proposal is open, its preview replaces the real sessions inside its window. */
export function withPreview(sessions: Session[], preview?: { start: string; end: string; sessions: Session[] }): Session[] {
  if (!preview) return sessions;
  const a = new Date(preview.start).getTime(), b = new Date(preview.end).getTime();
  // Events from connected calendars are never part of a proposal, so they stay as they are.
  const inside = (s: Session) => !s.external && new Date(s.starts_at).getTime() < b && new Date(s.ends_at).getTime() > a;
  return [...sessions.filter(s => !inside(s)), ...preview.sessions].sort((x, y) => x.starts_at.localeCompare(y.starts_at));
}

export function lowerFirst(text: string): string {
  return text ? text[0].toLowerCase() + text.slice(1) : text;
}
