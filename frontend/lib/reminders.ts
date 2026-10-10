export type Reminder = {
  id: string;
  title: string;
  due: string;
  completed: boolean;
};
export const REMINDERS_KEY = "getcracked.reminders.v1";

export function isReminderList(value: unknown): value is Reminder[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        item &&
        typeof item.id === "string" &&
        typeof item.title === "string" &&
        typeof item.completed === "boolean" &&
        typeof item.due === "string" &&
        (!item.due || Number.isFinite(new Date(item.due).getTime())),
    )
  );
}

export function sortReminders(items: Reminder[]) {
  return [...items].sort(
    (a, b) =>
      Number(a.completed) - Number(b.completed) ||
      (a.due ? new Date(a.due).getTime() : Infinity) -
        (b.due ? new Date(b.due).getTime() : Infinity),
  );
}
