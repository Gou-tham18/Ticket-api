import { ApiError } from './triageApi';
import { postJson, request } from './escalationApi';
import {
  ApprovalConfig,
  BatchPreview,
  BatchSendResult,
  ButtonSetting,
  Dashboard,
} from '../types/dashboard';

const BUTTON_SETTINGS: ButtonSetting[] = ['PUBLIC_BASE_URL', 'APPROVAL_LINK_SECRET'];

type Obj = Record<string, unknown>;

function isObject(value: unknown): value is Obj {
  return !!value && typeof value === 'object';
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isNullableString(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function isNullableNumber(value: unknown): boolean {
  return value === null || typeof value === 'number';
}

function isDecision(value: unknown): boolean {
  return value === 'Accept' || value === 'Reject';
}

export function isValidApprovalConfig(data: unknown): data is ApprovalConfig {
  return (
    isObject(data) &&
    typeof data.configured === 'boolean' &&
    typeof data.email_configured === 'boolean' &&
    // Older backends have no buttons fields; they are treated as not configured.
    (data.buttons_configured === undefined || typeof data.buttons_configured === 'boolean') &&
    (data.buttons_missing === undefined ||
      (isStringArray(data.buttons_missing) &&
        data.buttons_missing.every((name) => BUTTON_SETTINGS.includes(name as ButtonSetting)))) &&
    isNullableString(data.user_name) &&
    isNullableString(data.manager_name)
  );
}

function isValidDashboardTicket(ticket: unknown): boolean {
  return (
    isObject(ticket) &&
    typeof ticket.ticket_id === 'string' &&
    typeof ticket.is_open === 'boolean' &&
    isStringArray(ticket.labels) &&
    isStringArray(ticket.indicators) &&
    (ticket.decision === null || isDecision(ticket.decision)) &&
    isNullableString(ticket.decided_by) &&
    isNullableString(ticket.decided_at)
  );
}

function isValidBatchTicket(ticket: unknown): boolean {
  return (
    isValidDashboardTicket(ticket) &&
    isObject(ticket) &&
    typeof ticket.summary_line === 'string' &&
    (ticket.send_reason === 'new' || ticket.send_reason === 'reminder') &&
    isNullableString(ticket.last_emailed_at) &&
    isNullableNumber(ticket.days_waiting)
  );
}

function isValidWaitingTicket(ticket: unknown): boolean {
  return (
    isObject(ticket) &&
    typeof ticket.ticket_id === 'string' &&
    typeof ticket.summary_line === 'string' &&
    typeof ticket.last_emailed_at === 'string' &&
    typeof ticket.reminder_due_at === 'string'
  );
}

function isValidRecentDecision(decision: unknown): boolean {
  return (
    isObject(decision) &&
    typeof decision.ticket_id === 'string' &&
    isDecision(decision.decision) &&
    isNullableString(decision.decided_by) &&
    isNullableString(decision.decided_at)
  );
}

export function isValidDashboard(data: unknown): data is Dashboard {
  if (!isObject(data) || !isObject(data.attention) || !isObject(data.approval_batch)) {
    return false;
  }
  const attention = data.attention;
  const batch = data.approval_batch;
  return (
    typeof data.total_tickets === 'number' &&
    typeof data.open_tickets === 'number' &&
    ['urgent_open', 'escalated_label', 'refund_over_200', 'any_condition'].every(
      (key) => typeof attention[key] === 'number',
    ) &&
    Array.isArray(data.tickets) &&
    data.tickets.every(isValidDashboardTicket) &&
    typeof batch.count === 'number' &&
    typeof batch.fields_saved === 'number' &&
    Array.isArray(batch.tickets) &&
    batch.tickets.every(isValidBatchTicket) &&
    Array.isArray(data.waiting_for_reply) &&
    data.waiting_for_reply.every(isValidWaitingTicket) &&
    isNullableString(data.next_reminder_due_at) &&
    Array.isArray(data.recent_decisions) &&
    data.recent_decisions.every(isValidRecentDecision)
  );
}

export function isValidBatchPreview(data: unknown): data is BatchPreview {
  return (
    isObject(data) &&
    typeof data.subject === 'string' &&
    typeof data.text_body === 'string' &&
    typeof data.html_body === 'string' &&
    isStringArray(data.ticket_ids)
  );
}

export function isValidBatchSendResult(data: unknown): data is BatchSendResult {
  return (
    isObject(data) &&
    data.sent === true &&
    isStringArray(data.ticket_ids) &&
    isStringArray(data.newly_requested) &&
    isStringArray(data.reminders)
  );
}

function validated<T>(data: unknown, isValid: (value: unknown) => value is T): T {
  if (!isValid(data)) {
    throw new ApiError('Received a malformed response from the escalation service.');
  }
  return data;
}

export async function fetchApprovalConfig(): Promise<ApprovalConfig> {
  const config = validated(await request('/approvals/config'), isValidApprovalConfig);
  return {
    ...config,
    buttons_configured: config.buttons_configured ?? false,
    buttons_missing: config.buttons_missing ?? (config.buttons_configured ? [] : BUTTON_SETTINGS),
  };
}

export async function fetchDashboard(): Promise<Dashboard> {
  return validated(await request('/dashboard'), isValidDashboard);
}

export async function fetchBatchPreview(): Promise<BatchPreview> {
  return validated(await request('/approvals/batch/preview'), isValidBatchPreview);
}

export async function sendApprovalBatch(): Promise<BatchSendResult> {
  return validated(await postJson('/approvals/batch/send', {}), isValidBatchSendResult);
}
