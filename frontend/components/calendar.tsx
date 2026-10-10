"use client";
import { useEffect, useRef, useState } from "react";
import type { Session } from "../lib/types";
import { dateKey, dayLabel, minutesOfDay, clock } from "../lib/time";

export default function Calendar({ days, sessions, timezone, onSelect }: { days: string[]; sessions: Session[]; timezone: string; onSelect: (session: Session) => void }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const timer = setInterval(() => setNow(new Date()), 30000); return () => clearInterval(timer); }, []);
  const scroll = useRef<HTMLDivElement>(null);
  useEffect(() => { if (scroll.current) scroll.current.scrollTop = 7 * 56; }, []);
  return <div className="calendar-shell">
    <div className="calendar-head" style={{ gridTemplateColumns: `48px repeat(${days.length}, minmax(110px, 1fr))` }}>
      <div />
      {days.map(day => <div key={day} className={dateKey(new Date(), timezone) === day ? "today" : ""}><small>{dayLabel(day, { weekday: "short" })}</small><strong>{day.slice(-2)}</strong></div>)}
    </div>
    <div className="calendar-scroll" ref={scroll}><div className="calendar-grid" style={{ gridTemplateColumns: `48px repeat(${days.length}, minmax(110px, 1fr))` }}>
      <div className="hour-labels">{Array.from({ length: 24 }, (_, hour) => <span key={hour} style={{ top: hour * 56 }}>{hour === 0 ? "12a" : hour < 12 ? `${hour}a` : hour === 12 ? "12p" : `${hour - 12}p`}</span>)}</div>
      {days.map(day => <div key={day} className="calendar-day">
        {dateKey(now, timezone) === day && <div className="calendar-now" style={{top: minutesOfDay(now.toISOString(), timezone) / 60 * 56}} />}
        {sessions.filter(s => dateKey(s.starts_at, timezone) === day).map(s => {
          const start = minutesOfDay(s.starts_at, timezone);
          const end = dateKey(s.ends_at, timezone) === day ? minutesOfDay(s.ends_at, timezone) : 1440;
          return <button key={s.id} className={`calendar-event ${s.obligation_id ? "is-fixed" : "is-flexible"} ${s.status}`} style={{ top: start / 60 * 56, height: Math.max(23, (end - start) / 60 * 56 - 3) }} onClick={() => onSelect(s)} title={`${s.title} · ${clock(s.starts_at, timezone)} · ${s.status}`}>
            <strong>{s.locked ? "▣ " : ""}{s.title}</strong><small>{clock(s.starts_at, timezone)} · {s.obligation_id ? "Fixed" : s.status}</small>
          </button>;
        })}
      </div>)}
    </div></div>
  </div>;
}
