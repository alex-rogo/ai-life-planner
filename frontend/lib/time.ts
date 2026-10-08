export function dateKey(value: Date | string, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(value));
  const part = (name: string) => parts.find(p => p.type === name)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}
export function clock(value: string | Date, timezone: string): string {
  return new Intl.DateTimeFormat("en-US", { timeZone: timezone, hour: "numeric", minute: "2-digit" }).format(new Date(value));
}
export function dayLabel(day: string, options: Intl.DateTimeFormatOptions = { weekday: "short", month: "short", day: "numeric" }): string {
  return new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(new Date(`${day}T12:00:00Z`));
}
export function addDays(day: string, count: number): string {
  const date = new Date(`${day}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + count);
  return date.toISOString().slice(0, 10);
}
export function minutesOfDay(stamp: string, timezone: string): number {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(stamp));
  return Number(parts.find(p => p.type === "hour")!.value) * 60 + Number(parts.find(p => p.type === "minute")!.value);
}
export function zonedISO(day: string, time: string, timezone: string): string {
  const target = new Date(`${day}T${time}:00Z`).getTime();
  let guess = target;
  for (let i = 0; i < 4; i++) {
    const localDay = dateKey(new Date(guess), timezone);
    const minute = minutesOfDay(new Date(guess).toISOString(), timezone);
    const represented = new Date(`${localDay}T00:00:00Z`).getTime() + minute * 60000;
    const offset = target - represented;
    guess += offset;
    if (!offset) return new Date(guess).toISOString();
  }
  throw new Error("This local time does not exist because of daylight saving time.");
}
export function duration(session: { starts_at: string; ends_at: string }): number {
  return Math.round((new Date(session.ends_at).getTime() - new Date(session.starts_at).getTime()) / 60000);
}
export function hours(minutes: number): string {
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ""}` : `${minutes}m`;
}
