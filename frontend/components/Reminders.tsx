"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import {
  isReminderList,
  REMINDERS_KEY,
  sortReminders,
  type Reminder,
} from "@/lib/reminders";

export default function Reminders() {
  const [items, setItems] = useState<Reminder[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<"Upcoming" | "Completed" | "All">(
    "Upcoming",
  );
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [deleted, setDeleted] = useState<Reminder | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const load = window.requestAnimationFrame(() => {
      try {
        const saved = localStorage.getItem(REMINDERS_KEY);
        if (saved) {
          const parsed: unknown = JSON.parse(saved);
          if (!isReminderList(parsed)) throw new Error();
          setItems(parsed);
        }
      } catch {
        setError(
          "Saved reminders could not be loaded. Browser storage may be unavailable.",
        );
      }
      setLoaded(true);
    });
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => {
      window.cancelAnimationFrame(load);
      clearInterval(timer);
    };
  }, []);

  function save(next: Reminder[]) {
    setItems(next);
    try {
      localStorage.setItem(REMINDERS_KEY, JSON.stringify(next));
      setError("");
    } catch {
      setError(
        "Changes are available in this session, but could not be saved to this browser.",
      );
    }
  }

  function cancelEdit() {
    setEditing(null);
    setTitle("");
    setDue("");
  }
  const shown = sortReminders(items).filter(
    (item) =>
      filter === "All" ||
      (filter === "Completed" ? item.completed : !item.completed),
  );

  return (
    <div className="reminders-view">
      <div className="section-title">
        <div>
          <h2>Reminders</h2>
          <p>
            {items.filter((item) => !item.completed).length} upcoming · Saved in
            this browser
          </p>
        </div>
        <Icon name="bell" size={24} />
      </div>
      <form
        className="reminder-form"
        onSubmit={(event) => {
          event.preventDefault();
          const submittedDue = String(
            new FormData(event.currentTarget).get("due") ?? "",
          );
          if (!title.trim()) {
            input.current?.focus();
            return;
          }
          if (
            submittedDue &&
            !Number.isFinite(new Date(submittedDue).getTime())
          ) {
            setError("Choose a valid date and time.");
            return;
          }
          save(
            editing
              ? items.map((item) =>
                  item.id === editing
                    ? { ...item, title: title.trim(), due: submittedDue }
                    : item,
                )
              : [
                  ...items,
                  {
                    id: crypto.randomUUID(),
                    title: title.trim(),
                    due: submittedDue,
                    completed: false,
                  },
                ],
          );
          cancelEdit();
        }}
      >
        <label htmlFor="reminder-title">
          {editing ? "Edit reminder" : "New reminder"}
        </label>
        <input
          ref={input}
          id="reminder-title"
          placeholder="What do you need to remember?"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          required
          maxLength={500}
        />
        <div className="reminder-form-bottom">
          <div>
            <label htmlFor="reminder-due">
              Due date <span>Optional</span>
            </label>
            <input
              id="reminder-due"
              name="due"
              type="datetime-local"
              value={due}
              onChange={(event) => setDue(event.target.value)}
              onInput={(event) => setDue(event.currentTarget.value)}
            />
          </div>
          <div className="reminder-form-actions">
            {editing && (
              <button
                type="button"
                className="secondary-button"
                onClick={cancelEdit}
              >
                Cancel
              </button>
            )}
            <button className="primary-button" type="submit" disabled={!loaded}>
              <Icon name={editing ? "check" : "plus"} size={16} />
              {editing ? "Save" : "Add reminder"}
            </button>
          </div>
        </div>
      </form>
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      <div className="reminder-tabs" aria-label="Filter reminders">
        {(["Upcoming", "Completed", "All"] as const).map((tab) => (
          <button
            key={tab}
            aria-pressed={filter === tab}
            onClick={() => setFilter(tab)}
            className={filter === tab ? "active" : ""}
          >
            {tab}
          </button>
        ))}
      </div>
      {!loaded ? (
        <p className="empty-state">Loading reminders…</p>
      ) : shown.length === 0 ? (
        <div className="empty-state">
          <Icon name="bell" size={26} />
          <p>
            {filter === "Completed"
              ? "No completed reminders."
              : "No reminders to show."}
          </p>
        </div>
      ) : (
        <div className="reminder-list">
          {shown.map((item) => {
            const overdue =
              !item.completed &&
              !!item.due &&
              new Date(item.due).getTime() < now;
            return (
              <div
                key={item.id}
                className={`reminder-row ${item.completed ? "completed" : ""}`}
              >
                <input
                  className="reminder-check"
                  type="checkbox"
                  aria-label={`Complete ${item.title}`}
                  checked={item.completed}
                  onChange={() =>
                    save(
                      items.map((row) =>
                        row.id === item.id
                          ? { ...row, completed: !row.completed }
                          : row,
                      ),
                    )
                  }
                />
                <div className="reminder-info">
                  <strong>{item.title}</strong>
                  <span className={overdue ? "overdue" : ""}>
                    {overdue && "Overdue · "}
                    {item.due
                      ? new Date(item.due).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit",
                        })
                      : "No due date"}
                  </span>
                </div>
                <button
                  className="icon-button"
                  aria-label={`Edit ${item.title}`}
                  onClick={() => {
                    setEditing(item.id);
                    setTitle(item.title);
                    setDue(item.due);
                    input.current?.focus();
                  }}
                >
                  <Icon name="edit" size={16} />
                </button>
                <button
                  className="icon-button"
                  aria-label={`Delete ${item.title}`}
                  onClick={() => {
                    setDeleted(item);
                    save(items.filter((row) => row.id !== item.id));
                    if (editing === item.id) cancelEdit();
                  }}
                >
                  <Icon name="trash" size={16} />
                </button>
              </div>
            );
          })}
        </div>
      )}
      {deleted && (
        <div className="undo-message" role="status">
          Reminder deleted
          <button
            onClick={() => {
              save([...items, deleted]);
              setDeleted(null);
            }}
          >
            Undo
          </button>
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setDeleted(null)}
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      )}
      <p className="reminder-note">
        Saved in this browser only. Due dates use your device timezone; notifications are not enabled.
      </p>
    </div>
  );
}
