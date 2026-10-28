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
      let detailMsg =
        'Request validation failed. Please check that subject is within 500 characters and description within 10,000 characters.';
      try {
        const errorJson = await response.json();
        if (Array.isArray(errorJson?.detail) && errorJson.detail.length > 0) {
          const firstErr = errorJson.detail[0];
          const field = firstErr?.loc?.[firstErr.loc.length - 1] || 'Input';
          detailMsg = `Validation error on ${field}: ${firstErr?.msg || 'Invalid value.'}`;
        } else if (typeof errorJson?.detail === 'string') {
          detailMsg = errorJson.detail;
        }
      } catch {
        // Fall back to detailMsg
      }
      throw new ApiError(detailMsg, 422);
    }

    if (response.status === 502) {
      throw new ApiError(
        'The ticket triage service encountered a server error. Please try again later.',
        502,
      );
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

