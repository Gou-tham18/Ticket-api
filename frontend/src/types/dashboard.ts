import { ApprovalStage, Decision } from './escalation';

export type Indicator = 'urgent_open' | 'escalated_label' | 'refund_over_200';

// Setting names (never values) the backend reports as missing for the buttons.
export type ButtonSetting = 'PUBLIC_BASE_URL' | 'APPROVAL_LINK_SECRET';

// GET /approvals/config
export interface ApprovalConfig {
  user_name: string | null;
  manager_name: string | null;
  configured: boolean;
  email_configured: boolean;
  // Approve/Reject links need PUBLIC_BASE_URL and APPROVAL_LINK_SECRET.
  buttons_configured: boolean;
  buttons_missing: ButtonSetting[];
}

export interface DashboardTicket {
  ticket_id: string;
  category: string;
  priority: string;
  created_at: string;
  status: string;
  is_open: boolean;
  assigned_to: string | null;
  labels: string[];
  refund_amount: number | null;
  indicators: Indicator[];
  // Set for escalated tickets and for urgent open ones; null otherwise.
  approval_stage: ApprovalStage | null;
  decision: Decision | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_source: 'tracker' | 'prototype' | null;
}

export type SendReason = 'new' | 'reminder';

export interface BatchTicket extends DashboardTicket {
  approval_stage: ApprovalStage;
  // Same one-line format as the approval email.
  summary_line: string;
  send_reason: SendReason;
  // Null for new tickets.
  last_emailed_at: string | null;
  first_requested_at: string | null;
  days_waiting: number | null;
}

// Emailed, no decision yet, and not yet due for a reminder.
export interface WaitingTicket {
  ticket_id: string;
  category: string;
  summary_line: string;
  last_emailed_at: string;
  reminder_due_at: string;
}

// A decision recorded through the app (decision_log.csv).
export interface RecentDecision {
  ticket_id: string;
  category: string;
  decision: Decision;
  decided_by: string | null;
  decided_at: string | null;
}

// GET /dashboard
export interface Dashboard {
  total_tickets: number;
  open_tickets: number;
  attention: Record<Indicator | 'any_condition', number>;
  // Open tickets first, then resolved; oldest first within each.
  tickets: DashboardTicket[];
  approval_batch: {
    count: number;
    fields_saved: number;
    tickets: BatchTicket[];
  };
  reminder_days: number;
  link_days: number;
  waiting_for_reply: WaitingTicket[];
  next_reminder_due_at: string | null;
  // Newest first, at most 20.
  recent_decisions: RecentDecision[];
}

// GET /approvals/batch/preview
export interface BatchPreview {
  to: string;
  from: string;
  subject: string;
  // Same as text_body; kept for older clients.
  body: string;
  text_body: string;
  html_body: string;
  ticket_ids: string[];
}

// POST /approvals/batch/send
export interface BatchSendResult {
  sent: boolean;
  ticket_ids: string[];
  newly_requested: string[];
  reminders: string[];
  next_reminder_due_at: string | null;
}
