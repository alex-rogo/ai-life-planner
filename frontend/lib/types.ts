export interface Goal { id: string; title: string; description: string; deadline: string | null; }
export interface Task {
  id: string; title: string; description: string; goal_id: string | null;
  duration_minutes: number; completed_minutes: number; priority: number;
  status: "pending" | "completed" | "cancelled"; deadline: string | null; not_before: string | null;
  min_session_minutes: number; max_session_minutes: number;
  recurrence: "none" | "daily" | "weekly"; sessions_per_week: number; activity_apps: string[];
}
export interface Session {
  id: string; title: string; starts_at: string; ends_at: string;
  status: "planned" | "completed" | "missed" | "skipped"; locked: boolean;
  task_id: string | null; obligation_id: string | null; credited_minutes: number;
}
export interface Preferences {
  timezone: string; sleep_start: string; sleep_end: string;
  available_start: string; available_end: string; preferred_start: string; preferred_end: string;
  break_minutes: number; stability_weight: number; preferred_weight: number; break_weight: number;
  context_weight: number; spread_weight: number; monitoring_enabled: boolean;
}
export interface Obligation { id: string; title: string; weekdays: number[]; start_time: string; end_time: string; start_date: string | null; end_date: string | null; }
export interface Message { id: string; role: string; content: string; mode: string; }
export interface Suggestion { id: string; session_id: string; message: string; remaining_minutes: number; status: string; }
export interface SystemStatus {
  ai_mode: "demo" | "gemini"; gemini_configured: boolean; gemini_model: string;
  demo_commands: string[]; monitoring_enabled: boolean; agent_connected?: boolean; last_activity_at?: string | null;
  activity_state?: string; agent_token_configured?: boolean;
}
export interface Unscheduled { task_id: string; title: string; minutes: number; reason: string; }
export interface PlanResult { sessions: Session[]; unscheduled: Unscheduled[]; explanation: string; solver_status: string; }
export interface ChatResult { reply: string; mode: string; defaults: string[]; needs_clarification: boolean; plan: PlanResult | null; }
