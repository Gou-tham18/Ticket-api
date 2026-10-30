import { ApprovalStage } from './escalation';

export type Indicator = 'urgent_open' | 'escalated_label' | 'refund_over_200';

// GET /approvals/config
export interface ApprovalConfig {
  user_name: string | null;
  manager_name: string | null;
  configured: boolean;
  email_configured: boolean;
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
  // Only set for urgent open tickets.
  approval_stage: ApprovalStage | null;
}

export interface BatchTicket extends DashboardTicket {
  approval_stage: ApprovalStage;
  // Same one-line format as the approval email.
  summary_line: string;
}

// GET /dashboard
export interface Dashboard {
  total_tickets: number;
  open_tickets: number;
  attention: Record<Indicator | 'any_condition', number>;
  tickets: DashboardTicket[];
  approval_batch: {
    count: number;
    fields_saved: number;
    tickets: BatchTicket[];
  };
}

// GET /approvals/batch/preview
export interface BatchPreview {
  to: string;
  from: string;
  subject: string;
  body: string;
  ticket_ids: string[];
}

// POST /approvals/batch/send
export interface BatchSendResult {
  sent: boolean;
  ticket_ids: string[];
  newly_requested: string[];
  reminders: string[];
}

export type ReplyStatus =
  | 'accept'
  | 'reject'
  | 'blank'
  | 'unclear'
  | 'not_found'
  | 'not_awaiting';

export type ReplyDecision = 'accept' | 'reject' | 'blank' | 'unclear';

export interface ReplyTicket {
  ticket_id: string;
  decision: ReplyDecision;
  status: ReplyStatus;
  reason: string;
}

// POST /approvals/reply/preview and /approvals/reply/record
export interface ReplyResult {
  manager: string;
  tickets: ReplyTicket[];
  counts: Record<ReplyStatus, number>;
  // Only in the record response.
  recorded?: string[];
}
