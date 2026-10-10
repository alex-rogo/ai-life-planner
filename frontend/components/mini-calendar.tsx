"use client";
import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { addDays, dayLabel } from "../lib/time";

export default function MiniCalendar({ selected, today, onSelect }: { selected: string; today: string; onSelect: (day: string) => void }) {
  const [cursor, setCursor] = useState("");
  const month = cursor || selected.slice(0, 7);
  const first = month + "-01";
  const weekday = (new Date(first + "T12:00:00Z").getUTCDay() + 6) % 7;
  const start = addDays(first, -weekday);
  function move(offset: number) {
    const date = new Date(first + "T12:00:00Z");
    date.setUTCMonth(date.getUTCMonth() + offset);
    setCursor(date.toISOString().slice(0, 7));
  }
  return <section className="mini-calendar" aria-label="Choose date">
    <div className="mini-heading"><strong>{dayLabel(first, { month: "long", year: "numeric" })}</strong><button className="icon-button" aria-label="Previous month" onClick={() => move(-1)}><ChevronLeft size={15} /></button><button className="icon-button" aria-label="Next month" onClick={() => move(1)}><ChevronRight size={15} /></button></div>
    <div className="mini-grid">{["M", "T", "W", "T", "F", "S", "S"].map((label, i) => <span key={i}>{label}</span>)}
      {Array.from({length:42}, (_, i) => addDays(start, i)).map(day => <button key={day} aria-label={dayLabel(day, {month:"long",day:"numeric",year:"numeric"})} aria-pressed={day === selected} className={(day === selected ? "selected " : "") + (day === today ? "today " : "") + (!day.startsWith(month) ? "outside" : "")} onClick={() => { onSelect(day); setCursor(""); }}>{Number(day.slice(-2))}</button>)}
    </div>
  </section>;
}
