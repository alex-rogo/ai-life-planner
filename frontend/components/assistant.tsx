"use client";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { CHANGE_COLORS, lowerFirst } from "../lib/calendar";
import type { Message, Proposal, Suggestion, View } from "../lib/types";

const PLACEHOLDER: Record<View, string> = {
  day: "e.g. “Move my workout to tonight”", week: "e.g. “Reschedule my week”", month: "e.g. “I have a programming assignment due Friday”",
};
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Rotating status lines while Tomo works: one set for planning a request, one for applying.
const THINKING = {
  asking: [
    "Working out what would change…", "Shuffling your week like a deck of cards…", "Asking the calendar nicely…",
    "Finding the gaps between the gaps…", "Weighing deadlines against coffee breaks…", "Nudging blocks into place…",
    "Making sure nothing double-books…", "Almost there, tidying the edges…",
  ],
  updating: ["Updating your plan…", "Putting everything where it goes…", "Dusting off the calendar…"],
};

/** Bouncing dots and a shimmering line that cycles through playful status messages. */
export function Thinking({ asking }: { asking: boolean }) {
  const lines = asking ? THINKING.asking : THINKING.updating;
  const [index, setIndex] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setIndex(i => i + 1), 2200);
    return () => clearInterval(timer);
  }, []);
  const line = lines[index % lines.length];
  return (
    <div className="bubble thinking" role="status" aria-label={lines[0]}>
      <span className="dots" aria-hidden="true"><i /><i /><i /></span>
      <span key={line} className="thinking-text" aria-hidden="true">{line}</span>
    </div>
  );
}

/** Lead with the outcome in bold, as the design's "Done." replies do. */
function Reply({ text }: { text: string }) {
  const match = /^(Done|Undone|Discarded)\.\s*([\s\S]*)$/.exec(text);
  return match ? <span><strong>{match[1]}.</strong> {match[2]}</span> : <span>{text}</span>;
}

export function ProposalCard({ proposal, busy, onApply, onDiscard }: { proposal: Proposal; busy: boolean; onApply: () => void; onDiscard: () => void }) {
  const count = proposal.changes.filter(c => c.kind !== "Kept").length;
  const shown = proposal.changes.slice(0, 8);
  const card = useRef<HTMLDivElement>(null);
  // Bring the whole card, including Apply and Discard, into view when a proposal arrives.
  useEffect(() => { card.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [proposal.id]);
  return (
    <div className="proposal" role="group" aria-label="Proposed changes" ref={card}>
      <div className="proposal-head">
        <strong>Proposed: {lowerFirst(proposal.title)}</strong>
        <span>{count ? `${plural(count, "change")} · shown dashed on your calendar` : "Nothing on your calendar moves"}</span>
      </div>
      {shown.map((c, i) => (
        <div key={i} className="change">
          <span className="eyebrow" style={{ color: CHANGE_COLORS[c.kind] ?? "var(--muted)" }}>{c.kind}</span>
          <div style={{ minWidth: 0 }}><div className="title-sm">{c.title}</div><div className="meta">{c.detail}</div></div>
        </div>
      ))}
      {proposal.changes.length > shown.length && <div className="change meta">and {proposal.changes.length - shown.length} more</div>}
      <div className="proposal-foot">{proposal.footer}</div>
      <div className="actions">
        <button className="secondary" onClick={onDiscard} disabled={busy}>Discard</button>
        <button className="primary" onClick={onApply} disabled={busy}>{count ? `Apply ${plural(count, "change")}` : "Apply"}</button>
      </div>
    </div>
  );
}

function CheckIn({ suggestion, busy, onAnswer }: { suggestion: Suggestion; busy: boolean; onAnswer: (decision: "confirm" | "dismiss") => void }) {
  return (
    <div className="proposal" role="group" aria-label="Activity check-in">
      <div className="proposal-head"><strong>Check-in: didn’t get to it?</strong><span>From your activity companion · uncertain evidence</span></div>
      <div className="change"><div className="meta" style={{ fontSize: 13 }}>{suggestion.message}</div></div>
      <div className="actions">
        <button className="secondary" onClick={() => onAnswer("dismiss")} disabled={busy}>Keep plan</button>
        <button className="primary" onClick={() => onAnswer("confirm")} disabled={busy}>Reschedule {suggestion.remaining_minutes} min</button>
      </div>
    </div>
  );
}

/** A chip that runs an action instead of sending a message; `confirm` asks for a second click. */
export interface ChatTool { label: string; confirm?: string; run: () => void; }

interface Props {
  view: View; open: boolean; onToggle: () => void; inputRef: RefObject<HTMLInputElement | null>;
  briefLabel: string; brief: string; prompts: string[]; messages: Message[]; proposal: Proposal | null; suggestions: Suggestion[];
  asking: string; busy: boolean; error: string;
  tools?: ChatTool[];
  onSend: (text: string) => void; onDecide: (id: string, action: "apply" | "discard" | "undo") => void; onAnswer: (id: string, decision: "confirm" | "dismiss") => void;
}

export default function Assistant(props: Props) {
  const { view, open, onToggle, inputRef, briefLabel, brief, prompts, messages, proposal, suggestions, asking, busy, error, onSend, onDecide, onAnswer, tools = [] } = props;
  // A destructive tool chip asks for a second click within a few seconds.
  const [armed, setArmed] = useState("");
  useEffect(() => {
    if (!armed) return;
    const reset = setTimeout(() => setArmed(""), 4000);
    return () => clearTimeout(reset);
  }, [armed]);
  const use = (tool: ChatTool) => {
    if (tool.confirm && armed !== tool.label) { setArmed(tool.label); return; }
    setArmed(""); tool.run();
  };
  const [text, setText] = useState("");
  const thread = useRef<HTMLDivElement>(null);
  const pending = proposal?.status === "pending" ? proposal : null;
  const undoable = proposal?.status === "applied" && proposal.can_undo ? proposal : null;
  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight });
  }, [messages.length, asking, pending?.id, error]);
  const submit = (value: string) => { if (value.trim() && !busy) { onSend(value); setText(""); } };

  const items: ReactNode[] = messages.slice(-8).map(m => m.role === "user"
    ? <div key={m.id} className="bubble mine">{m.content}</div>
    : (
      <div key={m.id} className="bubble">
        <Reply text={m.content} />
        {undoable && m.proposal_id === undoable.id && m.content.startsWith("Done.") && (
          <button className="ghost" onClick={() => onDecide(undoable.id, "undo")} disabled={busy}>Undo</button>
        )}
      </div>
    ));

  return (
    <aside className={`assistant${open ? "" : " closed"}`} aria-label="Assistant">
      <div className="assistant-inner" aria-hidden={!open} inert={!open}>
        <div className="assistant-head">
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700 }}>Plan with Tomo</h2>
            <span className="meta">Say what changed. I’ll rework the {view}.</span>
          </div>
          <button className="icon-btn" aria-label="Collapse chat" aria-expanded="true" onClick={onToggle}>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>
          </button>
        </div>
        <div className="thread" ref={thread} aria-live="polite">
          {brief && <div className="bubble"><span><strong>{briefLabel}</strong> {brief}</span></div>}
          {items}
          {asking && <div className="bubble mine">{asking}</div>}
          {busy && <Thinking asking={!!asking} />}
          {suggestions.map(s => <CheckIn key={s.id} suggestion={s} busy={busy} onAnswer={d => onAnswer(s.id, d)} />)}
          {pending && !busy && <ProposalCard proposal={pending} busy={busy} onApply={() => onDecide(pending.id, "apply")} onDiscard={() => onDecide(pending.id, "discard")} />}
          {error && <div className="bubble error" role="alert">{error}</div>}
        </div>
        <div className="composer">
          <div className="chips">
            {prompts.map(p => <button key={p} className="suggest" onClick={() => submit(p)} disabled={busy} title={p}>{p}</button>)}
            {tools.map(t => (
              <button key={t.label} className={`suggest tool${armed === t.label ? " armed" : ""}`} onClick={() => use(t)} disabled={busy}>
                {armed === t.label ? t.confirm : t.label}
              </button>
            ))}
          </div>
          <div className="compose-row">
            <label htmlFor="tomo-command" className="sr-only">Tell Tomo what changed</label>
            <input id="tomo-command" ref={inputRef} className="field" value={text} placeholder={PLACEHOLDER[view]} autoComplete="off"
              onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === "Enter") submit(text); }} />
            <button className="send" aria-label="Send" onClick={() => submit(text)} disabled={busy || !text.trim()}>
              <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></svg>
            </button>
          </div>
          <span className="meta">Press <kbd>/</kbd> anywhere to type a change.</span>
        </div>
      </div>
      <button className="rail" aria-label="Expand chat: Plan with Tomo" aria-expanded="false" onClick={onToggle} tabIndex={open ? -1 : 0}>
        <span className="rail-icon"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6" /></svg></span>
        <span className="rail-label"><span>Plan with Tomo</span></span>
      </button>
    </aside>
  );
}
