import { expect, it } from "vitest";
import { TIMING, assignLanes, busyHours, choreograph, fitUnit, matchKeys, hourLabel, hourScale, isoWeek, layout, rangeFor, shift, shortClock, weekStart, withPreview, yAt } from "../lib/calendar";
import type { Session } from "../lib/types";

const TZ = "America/Los_Angeles";
const session = (over: Partial<Session>): Session => ({
  id: "a", title: "Q4 budget review", starts_at: "2026-10-09T17:30:00Z", ends_at: "2026-10-09T18:45:00Z",
  status: "planned", locked: false, task_id: "t", obligation_id: null, credited_minutes: 0,
  category: "focus", subtitle: null, deadline: null, change: null, ...over,
});

// Even 60px-per-hour scale from 7 am to 9 pm, as in the Day mockup.
const even = hourScale(Array.from({ length: 14 }, () => true), 7, 21, 60);

it("formats clocks and hour labels like the design", () => {
  expect(shortClock(630)).toBe("10:30");
  expect(shortClock(805)).toBe("1:25");
  expect(hourLabel(7)).toBe("7 am");
  expect(hourLabel(12)).toBe("12 pm");
  expect(hourLabel(21)).toBe("9 pm");
});

it("computes day, Monday-based week and six-week month ranges", () => {
  expect(weekStart("2026-10-09")).toBe("2026-10-05");
  expect(weekStart("2026-10-11")).toBe("2026-10-05");
  expect(rangeFor("week", "2026-10-09")).toEqual({ start: "2026-10-05", days: 7 });
  expect(rangeFor("month", "2026-10-20")).toEqual({ start: "2026-09-28", days: 42 });
  expect(shift("month", "2026-01-31", 1)).toBe("2026-02-01");
  expect(shift("week", "2026-10-09", -1)).toBe("2026-10-02");
  expect(isoWeek("2026-10-09")).toBe(41);
});

it("positions a block from the first visible hour and tags its state", () => {
  const before = new Date("2026-10-09T17:00:00Z");
  const [block] = layout([session({ deadline: "2026-10-10T06:00:00Z" })], "2026-10-09", TZ, even, before, false);
  expect(block.top).toBe(210);
  expect(block.height).toBe(75);
  expect(block.tag).toBe("Due today");
  const [done] = layout([session({})], "2026-10-09", TZ, even, new Date("2026-10-09T19:00:00Z"), false);
  expect(done.tag).toBe("Done");
  expect(layout([session({})], "2026-10-10", TZ, even, before, false)).toEqual([]);
});

it("overlays a pending proposal's preview only within its window", () => {
  const outside = session({ id: "keep", starts_at: "2026-10-20T17:00:00Z", ends_at: "2026-10-20T18:00:00Z" });
  const replaced = session({ id: "old" });
  const proposed = session({ id: "new", change: "Moved", starts_at: "2026-10-09T20:00:00Z", ends_at: "2026-10-09T21:15:00Z" });
  const merged = withPreview([replaced, outside], { start: "2026-10-09T07:00:00Z", end: "2026-10-16T07:00:00Z", sessions: [proposed] });
  expect(merged.map(s => s.id)).toEqual(["new", "keep"]);
  const [block] = layout(merged, "2026-10-09", TZ, even, new Date("2026-10-09T17:00:00Z"), true);
  expect(block.tag).toBe("Proposed · Moved");
  expect(block.proposed).toBe(true);
});

it("compresses empty hours so booked hours get the space, and still fits the window", () => {
  // 10:30-11:45 local is booked; every other hour from 7 am to 9 pm is empty.
  const busy = busyHours([session({})], ["2026-10-09"], TZ, 7, 21);
  expect(busy.filter(Boolean)).toHaveLength(2);
  expect(busy[3] && busy[4]).toBe(true);
  const unit = fitUnit(busy, 700, 30, 120, 60);
  const scale = hourScale(busy, 7, 21, unit);
  expect(scale.total).toBeLessThanOrEqual(700);
  expect(scale.offsets[4] - scale.offsets[3]).toBe(unit);
  expect(scale.offsets[1] - scale.offsets[0]).toBeLessThan(unit / 2);
  const [block] = layout([session({})], "2026-10-09", TZ, scale, new Date("2026-10-09T17:00:00Z"), false);
  expect(block.top).toBe(yAt(scale, 630));
  expect(block.height).toBe(Math.round(unit * 1.25));
  // With nothing booked the grid stays even, and without a measurement the fallback is used.
  expect(busyHours([], ["2026-10-09"], TZ, 7, 21).every(Boolean)).toBe(true);
  expect(fitUnit(busy, 0, 30, 120, 60)).toBe(60);
});

it("carries visual identity across a change, even when the solver recreates a row", () => {
  const before = [
    session({ id: "kept", task_id: "k" }),
    session({ id: "old-row", task_id: "m", starts_at: "2026-10-09T20:00:00Z", ends_at: "2026-10-09T21:00:00Z" }),
    session({ id: "gone", task_id: "g" }),
  ];
  // "kept" already carries an identity from an earlier change; the moved task got a new row id.
  const keys = matchKeys(before, { kept: "first-key" }, [
    session({ id: "kept", task_id: "k" }),
    session({ id: "new-row", task_id: "m", starts_at: "2026-10-10T20:00:00Z", ends_at: "2026-10-10T21:00:00Z" }),
    session({ id: "fresh", task_id: "f" }),
  ]);
  expect(keys).toEqual({ kept: "first-key", "new-row": "old-row", fresh: "fresh" });
});

it("stages a change: strike-and-fade removals, shifts with the scale, moves one by one, then new blocks", () => {
  const place = (key: string, col: number, start: number, end: number, title = "Q4 budget review") => ({
    session: session({ id: key, title }), key, col, start, end, top: start - 420, height: end - start,
    done: false, proposed: false, tag: "", kind: "plain" as const, lane: 0, lanes: 1,
  });
  const before = [place("gone", 0, 600, 660), place("same", 0, 480, 540), place("travels", 0, 720, 780)];
  const after = [
    { ...place("same", 0, 480, 540), top: 30 }, // only the hour scale changed
    place("travels", 2, 900, 960),
    place("fresh", 1, 600, 690, "Q4 slides"),
  ];
  const show = choreograph(before, after);
  const by = (key: string) => show.cues.find(c => c.key === key)!;
  expect(by("gone").phase).toBe("exit");
  expect(show.shiftAt).toBe(TIMING.strike + TIMING.fade);
  expect(by("same")).toMatchObject({ phase: "shift", delay: show.shiftAt });
  expect(by("travels")).toMatchObject({ phase: "move", col: 2, start: 900 });
  expect(by("travels").delay).toBeGreaterThan(show.shiftAt);
  const fresh = by("fresh");
  expect(fresh.phase).toBe("enter");
  expect(fresh.delay).toBeGreaterThanOrEqual(by("travels").delay + TIMING.move);
  expect(fresh.typeAt).toBe(fresh.delay + TIMING.typeLead);
  expect(show.duration).toBeGreaterThan(fresh.typeAt);
  // Many simultaneous moves are spread over a bounded time instead of queueing for seconds.
  const many = Array.from({ length: 40 }, (_, i) => place(`m${i}`, 0, 420 + i * 15, 435 + i * 15));
  const moved = choreograph(many, many.map(p => ({ ...p, col: 1 })));
  expect(Math.max(...moved.cues.map(c => c.delay))).toBeLessThanOrEqual(TIMING.shift + TIMING.moveSpread);
  // Nothing changed: everything stays.
  expect(choreograph([after[0]], [after[0]]).cues.map(c => c.phase)).toEqual(["stay"]);
});

it("puts overlapping blocks side by side and leaves the rest full width", () => {
  const b = (start: number, end: number) => ({ start, end, lane: 0, lanes: 1 });
  const [bus, cls, home, later] = assignLanes([b(570, 750), b(600, 720), b(720, 780), b(900, 960)]);
  expect([bus.lane, cls.lane, home.lane]).toEqual([0, 1, 1]);
  expect([bus.lanes, cls.lanes, home.lanes]).toEqual([2, 2, 2]);
  expect([later.lane, later.lanes]).toEqual([0, 1]);
});
