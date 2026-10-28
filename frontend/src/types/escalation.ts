export type ApprovalStage =
  | 'not_requested'
  | 'awaiting_decision'
  | 'accepted'
  | 'rejected';

export type OpenStatus = 'open' | 'in_progress';

export type Decision = 'Accept' | 'Reject';

export interface EscalationDetails {
  in_tracker: boolean;
  request_source: 'tracker' | 'prototype' | null;
  requested_by: string | null;
  approver: string | null;
  requested_at: string | null;
  tracker_decision_raw: string | null;
  decision: Decision | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_source: 'tracker' | 'prototype' | null;
  state: 'pending' | 'accepted' | 'rejected';
  notes: string | null;
}

export interface UrgentTicket {
  ticket_id: string;
  category: string;
  priority: string;
  created_at: string;
  status: string;
  is_open: boolean;
  assigned_to: string | null;
  // null when the ticket has no escalation tag and no tracker row.
  escalation: EscalationDetails | null;
  approval_stage: ApprovalStage;
  age_hours: number | null;
  waiting_for_decision_hours: number | null;
}

export interface UrgentOpenAnalysis {
  total: number;
  needs_action: number;
  by_stage: Record<ApprovalStage, number>;
  by_category: Record<string, number>;
  managers: string[];
  tickets: UrgentTicket[];
}

export interface UrgentOpenFilters {
  category?: string;
  status?: OpenStatus;
}

// JSON body for POST /approvals/{ticket_id}/request
export interface ApprovalRequestPayload {
  requested_by: string;
  approver: string;
}

// JSON body for POST /escalations/{ticket_id}/decision
export interface DecisionPayload {
  decision: Decision;
  decided_by: string;
}
