export type Category = "focus" | "routine" | "personal" | "errand";
export type View = "day" | "week" | "month";
export interface Goal { id: string; title: string; description: string; deadline: string | null; }
export interface Task {
  id: string; title: string; description: string; goal_id: string | null;
  duration_minutes: number; completed_minutes: number; priority: number;
  status: "pending" | "completed" | "cancelled"; deadline: string | null; not_before: string | null;
  min_session_minutes: number; max_session_minutes: number; category: Category;
  recurrence: "none" | "daily" | "weekly"; sessions_per_week: number; activity_apps: string[];
  window_start?: string | null; window_end?: string | null;
}
export interface Session {
  id: string; title: string; starts_at: string; ends_at: string;
  status: "planned" | "completed" | "missed" | "skipped"; locked: boolean;
  task_id: string | null; obligation_id: string | null; credited_minutes: number;
  category: Category | "fixed"; subtitle: string | null; deadline: string | null; change: string | null; travel?: boolean;
  /** Imported from a connected calendar: fixed and read-only. */
  external?: boolean;
}
export interface Preferences {
  timezone: string; sleep_start: string; sleep_end: string;
  available_start: string; available_end: string; preferred_start: string; preferred_end: string;
  break_minutes: number; stability_weight: number; preferred_weight: number; break_weight: number;
  context_weight: number; spread_weight: number; monitoring_enabled: boolean;
}
export type EventKind = "commitment" | "appointment" | "interview" | "personal";
export interface Obligation {
  id: string; title: string; kind: EventKind; weekdays: number[]; start_time: string; end_time: string;
  start_date: string | null; end_date: string | null; travel_minutes: number; travel_mode: string;
}
export interface Message { id: string; role: "user" | "assistant"; content: string; mode: string; proposal_id: string | null; options?: string[] | null; }
export interface Suggestion { id: string; session_id: string; message: string; remaining_minutes: number; status: string; }
export type Provider = "canvas" | "google" | "outlook" | "apple" | "other" | "demo";
export interface CalendarSource {
  id: string; name: string; provider: Provider; url_hint: string; last_synced_at: string | null; last_success_at: string | null; last_error: string; imported_file?: boolean;
  events: number; deadlines: number; all_day: number;
}
export interface SystemStatus {
  now: string; demo_clock: boolean; sample_data_tools?: boolean; calendars: { name: string; provider: Provider; last_synced_at: string | null; last_success_at: string | null; error: string }[]; ai_mode: "demo" | "gemini" | "deepseek"; gemini_configured: boolean; gemini_model: string; monitoring_enabled: boolean;
  agent_connected?: boolean; agent_token_configured?: boolean;
}
export interface Change { kind: string; title: string; detail: string; }
export interface Proposal {
  id: string; status: "pending" | "applied" | "discarded" | "undone"; message: string; title: string;
  changes: Change[]; footer: string; can_undo: boolean;
  preview: { start: string; end: string; sessions: Session[] };
}
export interface ChatResult { reply: string; mode: string; defaults: string[]; needs_clarification: boolean; proposal: Proposal | null; }
export interface Decision { reply: string; proposal: Proposal | null; }
export type UpcomingKind = "Appointment" | "Interview" | "Project" | "Personal" | "Assignment";
export interface Upcoming {
  kind: UpcomingKind; date: string; when: string; title: string; meta: string; note: string;
  obligation_id: string | null; goal_id: string | null; key: string; done: boolean;
}
export interface GoalProgress { id: string; title: string; pct: number; progress: string; meta: string; }
export interface Overview {
  timezone: string; start: string; days: number; headline: string; summary: string; brief: string;
  stats: { label: string; value: string }[]; upcoming: Upcoming[]; goals: GoalProgress[];
  deadlines: { date: string; title: string; kind: "task" | "goal" | "assignment" | "all_day" }[]; prompts: string[]; first_hour: number; last_hour: number;
}
