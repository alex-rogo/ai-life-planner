import { Check, LockKeyhole, CalendarDays, Circle } from "lucide-react";
import type { Session } from "../lib/types";
import { clock, hours, duration } from "../lib/time";

export default function SessionCard({ session, timezone, onSelect }: { session: Session; timezone: string; onSelect: (session: Session) => void }) {
  return <button className={`session-card ${session.obligation_id ? "is-fixed" : "is-flexible"} ${session.status}`} onClick={() => onSelect(session)}>
    <span className="session-time">{clock(session.starts_at, timezone)}<small>{hours(duration(session))}</small></span>
    <span className="session-line" />
    <span className="session-title"><strong>{session.title}</strong><small>{session.obligation_id ? "Fixed obligation" : session.status === "planned" ? "Flexible work session" : session.status}</small></span>
    <span className="session-icon">{session.status === "completed" ? <Check size={17} /> : session.locked ? <LockKeyhole size={16} /> : session.obligation_id ? <CalendarDays size={17} /> : <Circle size={17} />}</span>
  </button>;
}
