"use client";
import { useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import { addDays, dateKey, dayLabel, minutesOfDay } from "../lib/time";
import { CATEGORY, LEGEND, TIMING, busyHours, choreograph, fitUnit, hourLabel, hourScale, layout, shortClock, yAt, type Block, type Cue, type Placed, type Scale } from "../lib/calendar";
import type { Overview, Session } from "../lib/types";
import type { Stage } from "./planner";
import { useArrivals } from "../lib/arrivals";

interface Shared { timezone: string; sessions: Session[]; overview: Overview; today: string; }

// Space below the grid: the schedule card's bottom padding and border plus the page's bottom padding.
const BELOW_GRID = 50;

/**
 * Window height left below the grid, so hours stretch to fill a tall window. The calendar never
 * shrinks below readable hour heights; beyond that it extends down and the page scrolls.
 * Zero on narrow (stacked) layouts, which use fixed scales.
 */
function useAvailableHeight(ref: RefObject<HTMLElement | null>) {
  const [available, setAvailable] = useState(0);
  useEffect(() => {
    const grid = ref.current;
    if (!grid || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const top = grid.getBoundingClientRect().top + window.scrollY;
      const height = window.innerWidth > 1100 ? Math.floor(window.innerHeight - top - BELOW_GRID) : 0;
      setAvailable(a => (a === height ? a : height));
    };
    // Re-measure when the window resizes and when content above the grid changes height.
    const observer = new ResizeObserver(measure);
    observer.observe(grid.closest("main") ?? document.documentElement);
    window.addEventListener("resize", measure);
    const frame = requestAnimationFrame(measure);
    return () => { observer.disconnect(); window.removeEventListener("resize", measure); cancelAnimationFrame(frame); };
  }, [ref]);
  return available;
}

/** Deadlines and all-day items for one day: dark "due" chips, lighter chips for all-day notes. */
type Deadline = Overview["deadlines"][number];
const dueKey = (x: Deadline) => `${x.date}|${x.kind}|${x.title}`;
/** New deadlines grow into the DUE row; a row that just appeared fades its label in too. */
function useDueArrivals(overview: Overview, days: string[], scope: string) {
  const keys = overview.deadlines.filter(x => days.includes(x.date)).map(dueKey);
  const fresh = useArrivals(keys, scope);
  return { fresh, newRow: keys.length > 0 && keys.every(k => fresh.has(k)) };
}

function DueChips({ overview, day, limit, open, fresh }: { overview: Overview; day: string; limit?: number; open?: boolean; fresh?: Set<string> }) {
  const chip = (x: Deadline) => (
    <span key={`${x.kind}-${x.title}`} className={`due${x.kind === "all_day" ? " all-day" : ""}${fresh?.has(dueKey(x)) ? " arrive" : ""}`} title={x.kind === "all_day" ? `All day: ${x.title}` : `Due: ${x.title}`}>{x.title}</span>
  );
  const all = overview.deadlines.filter(x => x.date === day);
  if (!limit || all.length <= limit) return <>{all.map(chip)}</>;
  // The rest stay mounted and fold open, so expanding grows the row instead of popping chips in.
  return <>
    {all.slice(0, limit).map(chip)}
    <div className={`due-extra${open ? " open" : ""}`} aria-hidden={!open}><div>{all.slice(limit).map(chip)}</div></div>
    <span className={`due-more${open ? " hidden" : ""}`}>+{all.length - limit} more</span>
  </>;
}
const DUE_LIMIT = 2;

function Legend() {
  return <>{LEGEND.map(l => <span key={l.key} className="legend"><i style={{ background: l.color }} />{l.label}</span>)}</>;
}
/** Hour lines and labels; lines bordering only empty, compressed hours are quieter. */
function HourLines({ scale }: { scale: Scale }) {
  return <>{scale.offsets.map((top, i) => {
    const quiet = !scale.busy[i] && !scale.busy[i - 1];
    return <div key={i} className={`hour${quiet ? " quiet" : ""}`} style={{ top }}><span>{hourLabel(scale.first + i)}</span><div /></div>;
  })}</>;
}
function surface(block: Block): CSSProperties {
  const k = CATEGORY[block.session.category];
  return {
    // Trips are hatched so they read as time in transit, not an event.
    background: block.done ? "var(--done-bg)" : block.proposed ? "var(--proposed-bg)"
      : block.session.travel ? `repeating-linear-gradient(135deg, ${k.bg} 0 7px, var(--paper) 7px 12px)` : k.bg,
    // Same style either way so a confirmed proposal only fades its outline color.
    outline: block.proposed ? "2px dashed var(--accent)" : "2px dashed transparent",
  };
}
const TAG: Record<Block["kind"], CSSProperties> = {
  done: { background: "var(--done-tag)", color: "var(--muted)" },
  proposed: { background: "var(--accent-soft)", color: "var(--accent-ink)" },
  due: { background: "var(--due-bg)", color: "var(--due-ink)" },
  plain: {},
};
function NowLine({ minutes, scale }: { minutes: number; scale: Scale }) {
  if (minutes < scale.first * 60 || minutes > scale.last * 60) return null;
  return <div className="now" aria-hidden="true" style={{ top: yAt(scale, minutes) }}><span /><div /></div>;
}

/**
 * Cues for the blocks on screen. Without a show every block simply stays; with one, the blocks
 * that were on screen are laid out on their old scale and choreographed into the new layout.
 */
function cuesFor(after: Placed[], stage: Stage, place: (sessions: Session[], keys: Record<string, string>) => Placed[]): { cues: Cue[]; shiftAt: number } {
  const show = stage.before
    ? choreograph(place(stage.before.sessions, stage.before.keys), after)
    : { cues: after.map((p): Cue => ({ ...p, phase: "stay", delay: 0, typeAt: 0, ms: 0 })), shiftAt: 0 };
  // Render in one fixed order. If React reordered elements it would move them in the DOM, and a
  // moved element loses its running transition and jumps to its destination.
  return { cues: show.cues.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0)), shiftAt: show.shiftAt };
}

/** Inline motion for a cue: transitions for blocks that stay or travel, CSS animations for the rest. */
function motion(cue: Cue, staged: boolean): { className: string; style: CSSProperties } {
  if (!staged || cue.phase === "stay") {
    return { className: "", style: staged ? { transition: "background 400ms ease, outline-color 400ms ease" } : {} };
  }
  if (cue.phase === "exit") return { className: " exit", style: { ["--at" as string]: `${cue.delay}ms` } };
  if (cue.phase === "enter") {
    return { className: " enter", style: { ["--at" as string]: `${cue.delay}ms`, transition: ["top", "left", "height", "width"].map(p => `${p} ${TIMING.shift}ms ease`).join(", ") } };
  }
  const ms = cue.ms;
  const ease = cue.phase === "move" ? "cubic-bezier(0.65, 0, 0.35, 1)" : "ease";
  return {
    className: cue.phase === "move" ? " moving" : "",
    style: {
      transition: ["top", "left", "height", "width"].map(p => `${p} ${ms}ms ${ease} ${cue.delay}ms`).join(", ") + ", background 400ms ease, outline-color 400ms ease",
      // The lift shadow plays only while the block travels (see .block.moving).
      ["--move-at" as string]: `${cue.delay}ms`, ["--move-ms" as string]: `${ms}ms`,
    },
  };
}

/** Text that types itself in, one character at a time from `at` ms, with a caret while typing. */
function Typed({ text, at, caret }: { text: string; at: number; caret?: boolean }) {
  return (
    <>
      {[...text].map((ch, i) => <span key={i} className="typed" style={{ animationDelay: `${at + i * TIMING.perChar}ms` }}>{ch}</span>)}
      {caret && <span className="caret" aria-hidden="true" style={{ animationDelay: `${at}ms`, animationDuration: `${text.length * TIMING.perChar + 200}ms` }} />}
    </>
  );
}
/** How many lines of title fit in `space` px; more than one lets the title wrap. */
const fitLines = (space: number, lineHeight: number) => Math.max(1, Math.floor(space / lineHeight));
/** A block title that wraps onto as many lines as the box has room for, then ends with an ellipsis. */
function Name({ cue, text, lines, done }: { cue: Cue; text: string; lines: number; done: boolean }) {
  return (
    <span className={`name${lines > 1 ? " wrap" : ""}`} style={{ color: done ? "var(--muted)" : "var(--ink)", ...(lines > 1 ? { WebkitLineClamp: lines } : {}) }}>
      <span className="txt"><Text cue={cue} text={text} caret /></span>
    </span>
  );
}
/** Plain text normally; typed in when the block is entering during a show. */
function Text({ cue, text, offset = 0, caret }: { cue: Cue; text: string; offset?: number; caret?: boolean }) {
  return cue.phase === "enter" ? <Typed text={text} at={cue.typeAt + offset * TIMING.perChar} caret={caret} /> : <>{text}</>;
}

export function DayView({ day, timezone, sessions, overview, today, now, previewing, stage }: Shared & { day: string; now: Date; previewing: boolean; stage: Stage }) {
  const first = overview.first_hour, last = overview.last_hour;
  const grid = useRef<HTMLDivElement>(null);
  const available = useAvailableHeight(grid);
  // Booked hours never shrink below a comfortable reading height; the page scrolls instead.
  const place = (list: Session[], keys: Record<string, string>) => {
    const busy = busyHours(list, [day], timezone, first, last);
    const scale = hourScale(busy, first, last, fitUnit(busy, available, 88, 160, 92));
    return { scale, placed: layout(list, day, timezone, scale, now, previewing).map(b => ({ ...b, col: 0, key: keys[b.session.id] ?? b.session.id })) };
  };
  const { scale, placed } = place(sessions, stage.keys);
  const { cues, shiftAt } = cuesFor(placed, stage, (list, keys) => place(list, keys).placed);
  const staged = !!stage.before;
  const due = useDueArrivals(overview, [day], day);
  return (
    <section className="card schedule" aria-label={day === today ? "Today's schedule" : `Schedule for ${dayLabel(day)}`}>
      <div className="schedule-head"><h2>Schedule</h2><Legend /></div>
      {overview.deadlines.some(x => x.date === day) && <div className={`day-due${due.newRow ? " arrive-row" : ""}`}><span className="due-label">DUE</span><DueChips overview={overview} day={day} fresh={due.fresh} /></div>}
      <div className={`grid${staged ? " animating" : ""}`} ref={grid} style={{ height: scale.total, marginTop: 10, ["--shift-at" as string]: `${shiftAt}ms` }}>
        <HourLines scale={scale} />
        {cues.map(b => {
          // Layout follows the block's rendered height, since the hour scale changes with the window.
          const k = CATEGORY[b.session.category], h = Math.max(14, b.height - 3), short = h < 54, tight = h < 30;
          const sub = b.session.subtitle && !short ? ` · ${b.session.subtitle}` : "";
          const name = b.session.title, range = `${shortClock(b.start)}–${shortClock(b.end)}${sub}`;
          const m = motion(b, staged);
          const lines = short ? 1 : fitLines(h - 20 - 19, 21);
          return (
            <div key={b.key} className={`block${tight ? " tight" : ""}${m.className}`} data-testid="block" title={`${name} · ${shortClock(b.start)}–${shortClock(b.end)}`}
              style={{ ...surface(b), top: b.top, height: h, ["--lane" as string]: b.lane, ["--lanes" as string]: b.lanes, padding: tight ? "2px 12px" : short ? "6px 12px" : "10px 12px", ...m.style }}>
              <span className="bar" style={{ background: b.done ? "var(--done-bar)" : k.color }} />
              <div className="body" style={{ flexDirection: short ? "row" : "column", gap: short ? 10 : 2, alignItems: short ? "center" : "flex-start" }}>
                <Name cue={b} text={name} lines={lines} done={b.done} />
                <span className="range"><Text cue={b} text={range} offset={name.length} /></span>
              </div>
              {b.tag && <span className="tag" style={{ ...TAG[b.kind], ...(b.phase === "enter" ? { ["--tag-at" as string]: `${b.typeAt + (name.length + range.length) * TIMING.perChar}ms` } : {}) }}>{b.tag}</span>}
            </div>
          );
        })}
        {day === today && <NowLine minutes={minutesOfDay(now.toISOString(), timezone)} scale={scale} />}
      </div>
    </section>
  );
}

/** Week blocks share one layer over all seven columns so a block can travel between days. */
const DAY_WIDTH = "((100% - var(--axis) - 7 * var(--gap)) / 7)";
/** Overlapping blocks split their day's width into lanes with a 2px gutter. */
const columnLeft = (col: number, lane: number, lanes: number) =>
  `calc(var(--axis) + var(--gap) + ${col} * (${DAY_WIDTH} + var(--gap)) + 2px + ${lane} * (${DAY_WIDTH} - 2px) / ${lanes})`;
const columnWidth = (lanes: number) => `calc((${DAY_WIDTH} - 2px) / ${lanes} - 2px)`;

export function WeekView({ start, timezone, sessions, overview, today, now, previewing, stage, onOpenDay }: Shared & { start: string; now: Date; previewing: boolean; stage: Stage; onOpenDay: (day: string) => void }) {
  const first = overview.first_hour, last = overview.last_hour;
  const grid = useRef<HTMLDivElement>(null);
  const available = useAvailableHeight(grid);
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  // One scale for the whole week keeps the columns aligned: an hour stays full size if any day uses it.
  const place = (list: Session[], keys: Record<string, string>) => {
    const busy = busyHours(list, days, timezone, first, last);
    const scale = hourScale(busy, first, last, fitUnit(busy, available, 72, 130, 76));
    return { scale, placed: days.flatMap((d, col) => layout(list, d, timezone, scale, now, previewing).map(b => ({ ...b, col, key: keys[b.session.id] ?? b.session.id }))) };
  };
  const { scale, placed } = place(sessions, stage.keys);
  const { cues, shiftAt } = cuesFor(placed, stage, (list, keys) => place(list, keys).placed);
  const staged = !!stage.before;
  const todayCol = days.indexOf(today);
  const [allDue, setAllDue] = useState(false);
  const due = useDueArrivals(overview, days, start);
  const overflow = days.some(d => overview.deadlines.filter(x => x.date === d).length > DUE_LIMIT);
  return (
    <section className="card schedule" aria-label="This week's schedule">
      <div className="schedule-head"><h2>Schedule</h2><Legend /></div>
      {/* Pinned to the top of the window while the page scrolls through the hours. */}
      <div className="week-cols week-head">
        <div />
        {days.map(d => {
          const isToday = d === today, past = d < today;
          return (
            <button key={d} className="dayhead" onClick={() => onOpenDay(d)} aria-label={`Open ${dayLabel(d, { weekday: "long", month: "long", day: "numeric" })}`}>
              <span className="dow" style={{ color: isToday ? "var(--accent)" : undefined }}>{dayLabel(d, { weekday: "short" })}</span>
              <span className="pill-date" style={{ background: isToday ? "var(--accent)" : "transparent", color: isToday ? "var(--on-accent)" : past ? "var(--muted)" : "var(--ink)" }}>{Number(d.slice(8))}</span>
            </button>
          );
        })}
        {overview.deadlines.some(x => days.includes(x.date)) && <>
          <div className={`due-label${due.newRow ? " arrive-fade" : ""}`}>DUE</div>
          {days.map(d => <div key={d} className="due-cell"><DueChips overview={overview} day={d} limit={DUE_LIMIT} open={allDue} fresh={due.fresh} /></div>)}
          {overflow && (
            <div className="due-toggle">
              <button aria-expanded={allDue} onClick={() => setAllDue(o => !o)}>{allDue ? "Show less" : "Show all due dates"}</button>
            </div>
          )}
        </>}
      </div>
      <div className={`grid${staged ? " animating" : ""}`} ref={grid} style={{ height: scale.total, marginTop: 12, ["--shift-at" as string]: `${shiftAt}ms` }}>
        <HourLines scale={scale} />
        <div className="week-body week-cols">
          <div />
          {days.map((d, col) => (
            <div key={d} className="col" style={{ background: d === today ? "var(--today-col)" : "transparent" }}>
              {col === todayCol && <NowLine minutes={minutesOfDay(now.toISOString(), timezone)} scale={scale} />}
            </div>
          ))}
        </div>
        <div className="week-blocks">
          {cues.map(b => {
            const h = Math.max(12, b.height - 2), range = `${shortClock(b.start)}–${shortClock(b.end)}`;
            const m = motion(b, staged);
            return (
              <div key={b.key} className={`block${h < 24 ? " tight" : ""}${m.className}`} data-testid="block" title={`${b.session.title} · ${range}${b.tag ? ` · ${b.tag}` : ""}`}
                style={{ ...surface(b), top: b.top, height: h, left: columnLeft(b.col, b.lane, b.lanes), width: columnWidth(b.lanes), padding: h >= 32 ? "6px 8px" : h >= 22 ? "3px 8px" : "0 8px", ...m.style }}>
                <Name cue={b} text={b.session.title} lines={h < 24 ? 1 : fitLines(h - (h >= 32 ? 12 : 6) - (h >= 46 ? 16 : 0), 17.5)} done={b.done} />
                {h >= 46 && <span className="range"><Text cue={b} text={range} offset={b.session.title.length} /></span>}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export function MonthView({ start, month, timezone, sessions, overview, today, onOpenDay }: Shared & { start: string; month: string; onOpenDay: (day: string) => void }) {
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  const grid = useRef<HTMLDivElement>(null);
  // Six week rows sized to fit, after the weekday header and row gaps.
  const available = useAvailableHeight(grid);
  const row = available > 0 ? Math.min(160, Math.max(56, Math.floor((available - 44) / 6))) : 104;
  const fit = Math.max(1, Math.floor((row - 34) / 20));
  const byDay = new Map<string, Session[]>();
  for (const s of sessions) {
    if (s.status === "skipped" || s.status === "missed") continue;
    const key = dateKey(s.starts_at, timezone);
    byDay.set(key, [...(byDay.get(key) ?? []), s]);
  }
  return (
    <section className="card schedule" aria-label="This month's schedule">
      <div className="schedule-head"><h2>Schedule</h2><Legend /></div>
      <div className="month-grid" ref={grid} style={{ gridTemplateRows: `auto repeat(6, ${row}px)` }}>
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(d => <div key={d} className="month-dow">{d}</div>)}
        {days.map(d => {
          const list = byDay.get(d) ?? [], due = overview.deadlines.filter(x => x.date === d);
          const classes = ["month-cell", d.slice(0, 7) !== month ? "outside" : "", d === today ? "today" : ""].join(" ");
          return (
            <button key={d} className={classes} onClick={() => onOpenDay(d)} aria-label={`${dayLabel(d, { weekday: "long", month: "long", day: "numeric" })}: ${list.length} blocks`}>
              <span className="month-num">{Number(d.slice(8))}</span>
              {due.length > 0 && <DueChips overview={overview} day={d} />}
              {list.slice(0, fit).map(s => (
                <span key={s.id} className="chip" style={{ background: CATEGORY[s.category].bg, boxShadow: `inset 3px 0 0 ${CATEGORY[s.category].color}`, outline: s.change ? "1px dashed var(--accent)" : undefined }}>{s.title}</span>
              ))}
              {list.length > fit && <span className="more">+{list.length - fit} more</span>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
