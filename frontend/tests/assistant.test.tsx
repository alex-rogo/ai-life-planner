import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import Assistant, { ProposalCard, Thinking } from "../components/assistant";
import type { Proposal } from "../lib/types";

const proposal: Proposal = {
  id: "p1", status: "pending", message: "Move my workout to tonight.", title: "An updated plan for that task",
  footer: "Everything still fits.", can_undo: false,
  preview: { start: "2026-10-09T07:00:00Z", end: "2026-10-16T07:00:00Z", sessions: [] },
  changes: [
    { kind: "Moved", title: "Workout", detail: "Fri 12:00 pm → Fri 6:00 pm" },
    { kind: "Kept", title: "Computer science class", detail: "Fixed commitments stay put" },
  ],
};

it("summarizes a proposal and applies or discards it", async () => {
  const onApply = vi.fn(), onDiscard = vi.fn();
  render(<ProposalCard proposal={proposal} busy={false} onApply={onApply} onDiscard={onDiscard} />);
  expect(screen.getByText("Proposed: an updated plan for that task")).toBeInTheDocument();
  expect(screen.getByText("1 change · shown dashed on your calendar")).toBeInTheDocument();
  expect(screen.getByText("Fri 12:00 pm → Fri 6:00 pm")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Apply 1 change" }));
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(onApply).toHaveBeenCalledOnce();
  expect(onDiscard).toHaveBeenCalledOnce();
});

it("disables both choices while a decision is in flight", () => {
  render(<ProposalCard proposal={proposal} busy onApply={() => {}} onDiscard={() => {}} />);
  expect(screen.getByRole("button", { name: "Apply 1 change" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Discard" })).toBeDisabled();
});

it("shows a playful, rotating status while Tomo works", async () => {
  vi.useFakeTimers();
  render(<Thinking asking />);
  const status = screen.getByRole("status");
  expect(status).toHaveAccessibleName("Thinking it through…");
  expect(status).toHaveTextContent("Thinking it through…");
  act(() => { vi.advanceTimersByTime(2200); });
  expect(status).toHaveTextContent("Reading back what you’ve told me…");
  vi.useRealTimers();
});

it("runs tool chips, asking for a second click before destructive ones", async () => {
  const clear = vi.fn(), load = vi.fn();
  render(<Assistant view="week" open onToggle={() => {}} inputRef={{ current: null }} briefLabel="" brief="" prompts={[]}
    messages={[]} proposal={null} suggestions={[]} asking="" busy={false} error=""
    onSend={() => {}} onDecide={() => {}} onAnswer={() => {}}
    tools={[{ label: "Load sample data", run: load }, { label: "Clear the calendar", confirm: "Click again to clear everything", run: clear }]} />);
  await userEvent.click(screen.getByRole("button", { name: "Load sample data" }));
  expect(load).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "Clear the calendar" }));
  expect(clear).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Click again to clear everything" }));
  expect(clear).toHaveBeenCalledOnce();
});

it("offers the latest reply's options as buttons that send the answer", async () => {
  const send = vi.fn();
  const messages = [
    { id: "1", role: "user" as const, content: "four in a row", mode: "deepseek", proposal_id: null },
    { id: "2", role: "assistant" as const, content: "Which four days?", mode: "deepseek", proposal_id: null, options: ["Mon-Thu at 4 pm", "Fri-Mon at 4 pm"] },
  ];
  render(<Assistant view="week" open onToggle={() => {}} inputRef={{ current: null }} briefLabel="" brief="" prompts={[]}
    messages={messages} proposal={null} suggestions={[]} asking="" busy={false} error=""
    onSend={send} onDecide={() => {}} onAnswer={() => {}} tools={[]} />);
  await userEvent.click(screen.getByRole("button", { name: "Fri-Mon at 4 pm" }));
  expect(send).toHaveBeenCalledWith("Fri-Mon at 4 pm");
});
