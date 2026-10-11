import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { CalendarConnections } from "../components/dialogs";
import type { CalendarSource } from "../lib/types";

const canvas: CalendarSource = {
  id: "c1", name: "Canvas", provider: "canvas", url_hint: "school.instructure.com · ….ics",
  last_synced_at: "2026-10-13T15:00:00Z", last_error: "", events: 63, deadlines: 8, all_day: 1,
};
afterEach(() => vi.unstubAllGlobals());

function backend(sources: CalendarSource[]) {
  const calls: { path: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) => {
    calls.push({ path, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body as string) : undefined });
    if (init.method === "POST" && path === "/api/calendars") sources.push(canvas);
    return { ok: true, status: 200, json: async () => (path === "/api/calendars" ? sources : canvas) };
  }));
  return calls;
}

it("connects a Canvas feed and shows its status without the secret link", async () => {
  const calls = backend([]);
  const onChanged = vi.fn();
  render(<CalendarConnections demo={false} now="2026-10-13T15:05:00Z" onChanged={onChanged} />);
  expect(await screen.findByText("No calendars connected yet.")).toBeInTheDocument();
  expect(screen.getByText(/click “Calendar Feed”/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Feed link"), "https://school.instructure.com/feeds/calendars/user_SECRET.ics");
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(await screen.findByText(/63 events · 8 assignments · 1 all-day · synced 5 min ago/)).toBeInTheDocument();
  expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  expect(calls.find(c => c.method === "POST")?.body).toMatchObject({ provider: "canvas", url: expect.stringContaining("SECRET") });
  expect(onChanged).toHaveBeenCalled();
});

it("offers the demo Canvas feed only in demo mode", async () => {
  const calls = backend([]);
  const { unmount } = render(<CalendarConnections demo onChanged={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "Try the demo Canvas feed" }));
  expect(calls.find(c => c.method === "POST")?.body).toEqual({ provider: "demo", url: "demo://canvas" });
  unmount();
  backend([]);
  render(<CalendarConnections demo={false} onChanged={() => {}} />);
  await screen.findByText("No calendars connected yet.");
  expect(screen.queryByRole("button", { name: "Try the demo Canvas feed" })).not.toBeInTheDocument();
});
