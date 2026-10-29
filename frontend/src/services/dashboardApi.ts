import { ApiError } from './triageApi';
import { postJson, request } from './escalationApi';
import {
  ApprovalConfig,
  BatchPreview,
  BatchSendResult,
  Dashboard,
  ReplyResult,
  ReplyStatus,
} from '../types/dashboard';

const REPLY_STATUSES: ReplyStatus[] = [
  'accept',
  'reject',
  'blank',
  'unclear',
  'not_found',
  'not_awaiting',
];

type Obj = Record<string, unknown>;

function isObject(value: unknown): value is Obj {
  return !!value && typeof value === 'object';
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

export function isValidApprovalConfig(data: unknown): data is ApprovalConfig {
  return (
    isObject(data) &&
    typeof data.configured === 'boolean' &&
    typeof data.email_configured === 'boolean' &&
    (data.user_name === null || typeof data.user_name === 'string') &&
    (data.manager_name === null || typeof data.manager_name === 'string')
  );
}

function isValidDashboardTicket(ticket: unknown): boolean {
  return (
    isObject(ticket) &&
    typeof ticket.ticket_id === 'string' &&
    typeof ticket.is_open === 'boolean' &&
    isStringArray(ticket.labels) &&
    isStringArray(ticket.indicators)
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
    batch.tickets.every(
      (ticket) => isValidDashboardTicket(ticket) && typeof (ticket as Obj).summary_line === 'string',
    )
  );
}

export function isValidBatchPreview(data: unknown): data is BatchPreview {
  return (
    isObject(data) &&
    typeof data.subject === 'string' &&
    typeof data.body === 'string' &&
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

export function isValidReplyResult(data: unknown): data is ReplyResult {
  return (
    isObject(data) &&
    typeof data.manager === 'string' &&
    isObject(data.counts) &&
    Array.isArray(data.tickets) &&
    data.tickets.every(
      (ticket) =>
        isObject(ticket) &&
        typeof ticket.ticket_id === 'string' &&
        typeof ticket.reason === 'string' &&
        REPLY_STATUSES.includes(ticket.status as ReplyStatus),
    ) &&
    (data.recorded === undefined || isStringArray(data.recorded))
  );
}

function validated<T>(data: unknown, isValid: (value: unknown) => value is T): T {
  if (!isValid(data)) {
    throw new ApiError('Received a malformed response from the escalation service.');
  }
  return data;
}

export async function fetchApprovalConfig(): Promise<ApprovalConfig> {
  return validated(await request('/approvals/config'), isValidApprovalConfig);
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

export async function previewReply(replyText: string): Promise<ReplyResult> {
  return validated(
    await postJson('/approvals/reply/preview', { reply_text: replyText }),
    isValidReplyResult,
  );
}

export async function recordReply(replyText: string): Promise<ReplyResult> {
  return validated(
    await postJson('/approvals/reply/record', { reply_text: replyText }),
    isValidReplyResult,
  );
}
