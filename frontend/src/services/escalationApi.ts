import { ApiError, getApiBaseUrl, readErrorDetail } from './triageApi';
import {
  ApprovalRequestPayload,
  ApprovalStage,
  DecisionPayload,
  UrgentOpenAnalysis,
  UrgentOpenFilters,
} from '../types/escalation';

const APPROVAL_STAGES: ApprovalStage[] = [
  'not_requested',
  'awaiting_decision',
  'accepted',
  'rejected',
];

export function isValidUrgentOpenAnalysis(
  data: unknown,
): data is UrgentOpenAnalysis {
  if (!data || typeof data !== 'object') {
    return false;
  }

  const obj = data as Record<string, unknown>;
  const byStage = obj.by_stage as Record<string, unknown> | undefined;

  return (
    typeof obj.total === 'number' &&
    !!byStage &&
    typeof byStage === 'object' &&
    APPROVAL_STAGES.every((stage) => typeof byStage[stage] === 'number') &&
    Array.isArray(obj.managers) &&
    obj.managers.every((name) => typeof name === 'string') &&
    Array.isArray(obj.tickets) &&
    obj.tickets.every(
      (ticket) =>
        !!ticket &&
        typeof ticket === 'object' &&
        typeof (ticket as Record<string, unknown>).ticket_id === 'string' &&
        APPROVAL_STAGES.includes(
          (ticket as Record<string, unknown>).approval_stage as ApprovalStage,
        ),
    )
  );
}


export async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;

  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, init);
  } catch (_networkError) {
    throw new ApiError(
      'Unable to connect to the backend server. Please verify the backend service is running and accessible.',
    );
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    // FastAPI answers a missing route with a bare "Not Found"; the app's own
    // 404s say "ticket not found". A missing route means the server on this
    // port is an older build or a different app.
    if (response.status === 404 && detail === 'Not Found') {
      throw new ApiError(
        `The backend at ${getApiBaseUrl()} does not provide ${path.split('?')[0]}. It may be an outdated or different server — restart it from this project (uvicorn app.main:app --reload).`,
        response.status,
      );
    }
    throw new ApiError(
      detail ??
        `Server returned an error (${response.status}). Please try again later.`,
      response.status,
    );
  }

  try {
    return await response.json();
  } catch (_jsonError) {
    throw new ApiError(
      'Received an unreadable or non-JSON response from the server.',
      response.status,
    );
  }
}

export function postJson(path: string, body: unknown): Promise<unknown> {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function fetchUrgentOpen(
  filters: UrgentOpenFilters = {},
): Promise<UrgentOpenAnalysis> {
  const params = new URLSearchParams();
  if (filters.category) {
    params.set('category', filters.category);
  }
  if (filters.status) {
    params.set('status', filters.status);
  }
  const query = params.toString();

  const data = await request(`/approvals/urgent-open${query ? `?${query}` : ''}`);

  if (!isValidUrgentOpenAnalysis(data)) {
    throw new ApiError(
      'Received a malformed response from the escalation service.',
    );
  }
  return data;
}

export async function requestApproval(
  ticketId: string,
  payload: ApprovalRequestPayload,
): Promise<void> {
  await postJson(
    `/approvals/${encodeURIComponent(ticketId)}/request`,
    payload,
  );
}

export async function recordDecision(
  ticketId: string,
  payload: DecisionPayload,
): Promise<void> {
  await postJson(
    `/escalations/${encodeURIComponent(ticketId)}/decision`,
    payload,
  );
}
