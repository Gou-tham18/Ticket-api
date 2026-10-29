import { TriageRequest, TriageResult } from '../types/triage';

export class ApiError extends Error {
  statusCode?: number;
  userMessage: string;

  constructor(userMessage: string, statusCode?: number) {
    super(userMessage);
    this.name = 'ApiError';
    this.userMessage = userMessage;
    this.statusCode = statusCode;
  }
}

/**
 * The user-facing message in a FastAPI error body, or null if there is none.
 *
 * - `message`: the backend's plain first validation problem.
 * - `detail` string: HTTPException messages; a 500 adds its `error_id`.
 * - `detail` list: field errors from older backends without `message`.
 */
export async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const body = await response.json();
    if (typeof body?.message === 'string' && body.message) {
      return body.message;
    }
    if (typeof body?.detail === 'string') {
      return typeof body.error_id === 'string'
        ? `${body.detail} (Error ID: ${body.error_id})`
        : body.detail;
    }
    if (Array.isArray(body?.detail) && body.detail.length > 0) {
      const first = body.detail[0];
      const field = first?.loc?.[first.loc.length - 1] || 'input';
      return `Validation error on ${field}: ${first?.msg || 'Invalid value.'}`;
    }
  } catch {
    // Fall through to the caller's generic message.
  }
  return null;
}

const VALID_CATEGORIES = [
  'Billing',
  'Login',
  'Shipping',
  'Refunds',
  'Technical',
  'Account',
];

const VALID_PRIORITIES = ['urgent', 'high', 'normal', 'low'];

export function isValidTriageResult(data: unknown): data is TriageResult {
  if (!data || typeof data !== 'object') {
    return false;
  }

  const obj = data as Record<string, unknown>;

  const hasValidCategory =
    typeof obj.category === 'string' && VALID_CATEGORIES.includes(obj.category);
  const hasValidPriority =
    typeof obj.priority === 'string' && VALID_PRIORITIES.includes(obj.priority);
  const hasValidReply = typeof obj.suggested_reply === 'string';
  const hasValidArticles =
    Array.isArray(obj.article_ids) &&
    obj.article_ids.every((id) => typeof id === 'string');

  return (
    hasValidCategory && hasValidPriority && hasValidReply && hasValidArticles
  );
}

export function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (typeof envUrl === 'string' && envUrl.trim().length > 0) {
    return envUrl.trim().replace(/\/+$/, '');
  }
  return 'http://127.0.0.1:8000';
}

export async function submitTriage(
  requestData: TriageRequest,
): Promise<TriageResult> {
  const trimmedSubject = requestData.subject.trim();
  const trimmedText = requestData.text.trim();

  if (!trimmedSubject || !trimmedText) {
    throw new ApiError(
      'Both subject and ticket description are required.',
      400,
    );
  }

  const baseUrl = getApiBaseUrl();
  let response: Response;

  try {
    response = await fetch(`${baseUrl}/triage`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        subject: trimmedSubject,
        text: trimmedText,
      }),
    });
  } catch (_networkError) {
    throw new ApiError(
      'Unable to connect to the backend server. Please verify the backend service is running and accessible.',
    );
  }

  if (!response.ok) {
    if (response.status === 422) {
      const detail = await readErrorDetail(response);
      throw new ApiError(
        detail ??
          'Request validation failed. Please check that subject is within 500 characters and description within 10,000 characters.',
        422,
      );
    }

    if (response.status === 502) {
      throw new ApiError(
        'The ticket triage service encountered a server error. Please try again later.',
        502,
      );
    }

    // 503 explains what is not configured; 500 carries an error ID.
    if (response.status === 503 || response.status === 500) {
      const detail = await readErrorDetail(response);
      if (detail) {
        throw new ApiError(detail, response.status);
      }
    }

    throw new ApiError(
      `Server returned an error (${response.status}). Please try again later.`,
      response.status,
    );
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch (_jsonError) {
    throw new ApiError(
      'Received an unreadable or non-JSON response from the server.',
      response.status,
    );
  }

  if (!isValidTriageResult(data)) {
    throw new ApiError(
      'Received a malformed response from the triage service. Required result fields are missing or invalid.',
    );
  }

  return data;
}

