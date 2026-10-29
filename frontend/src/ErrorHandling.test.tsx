import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import App from './App';
import { EscalationDashboard } from './components/EscalationDashboard';
import { EscalationTracker } from './components/EscalationTracker';
import { getApiBaseUrl, readErrorDetail } from './services/triageApi';

vi.stubEnv('VITE_API_BASE_URL', getApiBaseUrl());

function jsonResponse(body: unknown, status: number): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const SERVER_ERROR = {
  detail:
    'Something went wrong on the server. Please try again, and if it keeps happening, report the time and this error ID.',
  error_id: 'a1b2c3d4',
};

describe('Error messages from the backend', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = '';
  });

  it('shows the triage 503 message instead of the generic text', async () => {
    const detail =
      'Ticket triage is not configured: GEMINI_API_KEY is not set. Add it to the backend .env file or the Render service environment, then restart the backend.';
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse({ detail }, 503));
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText(/subject/i), 'Cannot log in');
    await user.type(screen.getByLabelText(/ticket description/i), 'Reset email never arrives');
    await user.click(screen.getByRole('button', { name: /submit for triage/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Ticket triage is not configured');
    expect(alert).not.toHaveTextContent('Server returned an error (503)');
  });

  it('shows the triage 500 message with the error ID', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse(SERVER_ERROR, 500));
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText(/subject/i), 'Cannot log in');
    await user.type(screen.getByLabelText(/ticket description/i), 'Reset email never arrives');
    await user.click(screen.getByRole('button', { name: /submit for triage/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('(Error ID: a1b2c3d4)');
  });

  it('shows the dashboard 500 message with the error ID', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) =>
      String(input).endsWith('/approvals/config')
        ? jsonResponse(
            { user_name: 'Riya', manager_name: 'Mara', configured: true, email_configured: true },
            200,
          )
        : jsonResponse(SERVER_ERROR, 500),
    );
    render(<EscalationDashboard />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Something went wrong on the server.');
    expect(alert).toHaveTextContent('(Error ID: a1b2c3d4)');
  });

  it('shows the tracker 500 message with the error ID', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(SERVER_ERROR, 500));
    render(<EscalationTracker />);

    expect(await screen.findByRole('alert')).toHaveTextContent('(Error ID: a1b2c3d4)');
  });

  it('shows the 503 for a locked log file', async () => {
    const detail = 'Could not save to decision_log.csv. Close it if it is open in Excel and try again.';
    expect(await readErrorDetail(jsonResponse({ detail }, 503))).toBe(detail);
  });

  it('prefers the plain validation message and still reads older bodies', async () => {
    expect(
      await readErrorDetail(
        jsonResponse(
          {
            detail: [{ loc: ['body', 'subject'], msg: 'subject is required.', type: 'missing' }],
            message: 'subject is required.',
          },
          422,
        ),
      ),
    ).toBe('subject is required.');
    expect(
      await readErrorDetail(
        jsonResponse({ detail: [{ loc: ['body', 'subject'], msg: 'Field required' }] }, 422),
      ),
    ).toBe('Validation error on subject: Field required');
  });
});
