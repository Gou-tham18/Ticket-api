import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import App from './App';
import { EscalationDashboard } from './components/EscalationDashboard';
import { formatCreated } from './components/DashboardTicketTable';
import { getApiBaseUrl } from './services/triageApi';
import {
  ApprovalConfig,
  BatchTicket,
  Dashboard,
  DashboardTicket,
  ReplyResult,
} from './types/dashboard';

const BASE_URL = getApiBaseUrl();
vi.stubEnv('VITE_API_BASE_URL', BASE_URL);

function ticket(overrides: Partial<DashboardTicket>): DashboardTicket {
  return {
    ticket_id: 'TCK-0000',
    category: 'Billing',
    priority: 'normal',
    created_at: '2026-10-05 13:05',
    status: 'open',
    is_open: true,
    assigned_to: 'riya',
    labels: [],
    refund_amount: null,
    indicators: [],
    approval_stage: null,
    ...overrides,
  };
}

function batchTicket(overrides: Partial<BatchTicket>): BatchTicket {
  return {
    ...ticket({ priority: 'urgent', indicators: ['urgent_open'] }),
    approval_stage: 'not_requested',
    summary_line: 'TCK-0000 | Billing | urgent | created 05/10/2026 13:05',
    ...overrides,
  };
}

const BATCH = [
  batchTicket({
    ticket_id: 'TCK-5007',
    approval_stage: 'awaiting_decision',
    summary_line:
      'TCK-5007 | Refunds | urgent | created 05/10/2026 13:05 | in_progress | assigned to riya | labels escalated | refund 480.00',
  }),
  batchTicket({
    ticket_id: 'TCK-5110',
    summary_line:
      'TCK-5110 | Billing | urgent | created 11/10/2026 14:15 | open | assigned to lia | labels escalated, vip | refund 199.00',
  }),
];

// Counts deliberately differ from the rows to prove they come from the API.
function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    total_tickets: 120,
    open_tickets: 79,
    attention: { urgent_open: 10, escalated_label: 23, refund_over_200: 7, any_condition: 25 },
    tickets: [
      ticket({
        ticket_id: 'TCK-5007',
        priority: 'urgent',
        status: 'in_progress',
        labels: ['escalated'],
        refund_amount: 480,
        indicators: ['urgent_open', 'escalated_label', 'refund_over_200'],
        approval_stage: 'awaiting_decision',
      }),
      ticket({ ticket_id: 'TCK-5084', category: 'Login' }),
      ticket({ ticket_id: 'TCK-5043', status: 'resolved', is_open: false }),
    ],
    approval_batch: { count: 2, fields_saved: 16, tickets: BATCH },
    ...overrides,
  };
}

const CONFIG: ApprovalConfig = {
  user_name: 'Riya',
  manager_name: 'Mara',
  configured: true,
  email_configured: true,
};

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

type Routes = Record<string, () => Response>;

// Routes "METHOD /path" to a response; the query string is ignored.
function mockFetch(routes: Routes) {
  return vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(BASE_URL, '').split('?')[0];
      const key = `${init?.method ?? 'GET'} ${path}`;
      const handler = routes[key];
      if (!handler) {
        throw new Error(`Unexpected request ${key}`);
      }
      return handler();
    });
}

function defaultRoutes(overrides: Routes = {}): Routes {
  return {
    'GET /approvals/config': () => jsonResponse(CONFIG),
    'GET /dashboard': () => jsonResponse(dashboard()),
    ...overrides,
  };
}

function calls(spy: ReturnType<typeof mockFetch>, key: string) {
  return spy.mock.calls.filter(([input, init]) => {
    const path = String(input).replace(BASE_URL, '').split('?')[0];
    return `${(init as RequestInit | undefined)?.method ?? 'GET'} ${path}` === key;
  });
}

async function renderLoaded() {
  render(<EscalationDashboard />);
  await screen.findByTestId('attention-sentence');
}

function replyResult(overrides: Partial<ReplyResult> = {}): ReplyResult {
  return {
    manager: 'Mara',
    tickets: [
      { ticket_id: 'TCK-5007', decision: 'accept', status: 'accept', reason: 'Accept will be recorded.' },
      { ticket_id: 'TCK-5110', decision: 'blank', status: 'blank', reason: 'No decision written; stays awaiting.' },
      { ticket_id: 'TCK-9999', decision: 'reject', status: 'not_found', reason: 'Not in the Help Desk export.' },
    ],
    counts: { accept: 1, reject: 0, blank: 1, unclear: 0, not_found: 1, not_awaiting: 0 },
    ...overrides,
  };
}

describe('Escalation Dashboard', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = '';
  });

  it('opens from the navigation at #/dashboard', async () => {
    mockFetch(defaultRoutes());
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('link', { name: /escalation dashboard/i }));

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Escalation Dashboard' }),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe('#/dashboard');
    expect(screen.getByRole('link', { name: /escalation dashboard/i })).toHaveAttribute(
      'aria-current',
      'page',
    );
    // The other two pages are still linked.
    expect(screen.getByRole('link', { name: /ai ticket triage/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /escalation tracker/i })).toBeInTheDocument();
  });

  it('shows the sender and manager and the attention counts', async () => {
    mockFetch(defaultRoutes());
    await renderLoaded();

    expect(screen.getByTestId('sending-as')).toHaveTextContent('Sending as Riya → to Mara');
    expect(screen.getByText(/sensitive details/i)).toBeInTheDocument();
    expect(screen.getByTestId('attention-urgent_open')).toHaveTextContent('Urgent & open10');
    expect(screen.getByTestId('attention-escalated_label')).toHaveTextContent('23');
    expect(screen.getByTestId('attention-refund_over_200')).toHaveTextContent('7');
    expect(screen.getByTestId('attention-sentence')).toHaveTextContent(
      '25 open tickets match at least one condition.',
    );
    expect(screen.getByText(/for information only/i)).toBeInTheDocument();
  });

  it('lists the batch in email format with the fields-saved line', async () => {
    mockFetch(defaultRoutes());
    await renderLoaded();

    const list = screen.getByRole('list', { name: /next approval email/i });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(list).toHaveTextContent(BATCH[0].summary_line);
    expect(within(list).getByText('Reminder')).toBeInTheDocument();
    expect(within(list).getByText('New request')).toBeInTheDocument();
    expect(screen.getByTestId('fields-saved')).toHaveTextContent(
      "2 escalations prepared automatically: 16 ticket fields that didn't need to be copied by hand (2 tickets × 8 fields)",
    );
  });

  it('previews the email', async () => {
    mockFetch(
      defaultRoutes({
        'GET /approvals/batch/preview': () =>
          jsonResponse({
            to: 'Mara',
            from: 'Riya',
            subject: 'Urgent tickets awaiting your approval (2)',
            body: 'Hi Mara,\n\nTCK-5007 | Refunds\nDecision:\n',
            ticket_ids: ['TCK-5007', 'TCK-5110'],
          }),
      }),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Preview email' }));

    expect(
      await screen.findByText('Urgent tickets awaiting your approval (2)'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Hi Mara,/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide email preview' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('sends the batch, shows the result, and reloads', async () => {
    const spy = mockFetch(
      defaultRoutes({
        'POST /approvals/batch/send': () =>
          jsonResponse({
            sent: true,
            ticket_ids: ['TCK-5007', 'TCK-5110'],
            newly_requested: ['TCK-5110'],
            reminders: ['TCK-5007'],
          }),
      }),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Send to manager for approval' }));

    const banner = await screen.findByRole('status', { name: '' });
    expect(banner).toHaveTextContent('Email sent to Mara with 2 tickets.');
    expect(banner).toHaveTextContent('Newly requested: TCK-5110. Reminders: TCK-5007.');
    expect(calls(spy, 'POST /approvals/batch/send')).toHaveLength(1);
    await waitFor(() => expect(calls(spy, 'GET /dashboard')).toHaveLength(2));
  });

  it('disables sending when the batch is empty', async () => {
    mockFetch(
      defaultRoutes({
        'GET /dashboard': () =>
          jsonResponse(dashboard({ approval_batch: { count: 0, fields_saved: 0, tickets: [] } })),
      }),
    );
    await renderLoaded();

    expect(screen.getByText('No urgent open tickets need a decision.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send to manager for approval' })).toBeDisabled();
    expect(screen.queryByTestId('fields-saved')).not.toBeInTheDocument();
  });

  it('warns and disables send and record when not configured', async () => {
    mockFetch(
      defaultRoutes({
        'GET /approvals/config': () =>
          jsonResponse({
            user_name: null,
            manager_name: null,
            configured: false,
            email_configured: false,
          }),
      }),
    );
    await renderLoaded();

    expect(await screen.findByText(/not configured on the backend/i)).toBeInTheDocument();
    expect(screen.queryByTestId('sending-as')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send to manager for approval' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check reply' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Record decisions' })).toBeDisabled();
  });

  it('checks a reply, then records it with the same text', async () => {
    const spy = mockFetch(
      defaultRoutes({
        'POST /approvals/reply/preview': () => jsonResponse(replyResult()),
        'POST /approvals/reply/record': () =>
          jsonResponse(
            replyResult({
              tickets: [
                { ticket_id: 'TCK-5007', decision: 'accept', status: 'accept', reason: 'Accept recorded.' },
              ],
              recorded: ['TCK-5007'],
            }),
          ),
      }),
    );
    const user = userEvent.setup();
    await renderLoaded();
    const record = screen.getByRole('button', { name: 'Record decisions' });
    expect(record).toBeDisabled();

    const textarea = screen.getByLabelText("Paste the manager's reply here");
    await user.type(textarea, 'TCK-5007 Decision: APPROVE');
    await user.click(screen.getByRole('button', { name: 'Check reply' }));

    const row = await screen.findByTestId('reply-row-TCK-5007');
    expect(row).toHaveTextContent('Approve');
    expect(row).toHaveTextContent('Will accept');
    expect(screen.getByTestId('reply-row-TCK-5110')).toHaveTextContent('Blank');
    expect(screen.getByTestId('reply-row-TCK-9999')).toHaveTextContent(
      'Not foundNot in the Help Desk export.',
    );
    expect(record).toBeEnabled();

    await user.click(record);

    expect(await screen.findByText(/Recorded 1 decision by Mara: TCK-5007/)).toBeInTheDocument();
    const [, init] = calls(spy, 'POST /approvals/reply/record')[0];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      reply_text: 'TCK-5007 Decision: APPROVE',
    });
    expect(textarea).toHaveValue('');
    expect(record).toBeDisabled();
    await waitFor(() => expect(calls(spy, 'GET /dashboard')).toHaveLength(2));
  });

  it('keeps Record disabled when the preview has no decisions or the text changes', async () => {
    mockFetch(
      defaultRoutes({
        'POST /approvals/reply/preview': () =>
          jsonResponse(
            replyResult({
              tickets: [
                { ticket_id: 'TCK-5007', decision: 'blank', status: 'blank', reason: 'No decision.' },
              ],
              counts: { accept: 0, reject: 0, blank: 1, unclear: 0, not_found: 0, not_awaiting: 0 },
            }),
          ),
      }),
    );
    const user = userEvent.setup();
    await renderLoaded();
    const textarea = screen.getByLabelText("Paste the manager's reply here");

    await user.type(textarea, 'TCK-5007 Decision:');
    await user.click(screen.getByRole('button', { name: 'Check reply' }));
    await screen.findByTestId('reply-row-TCK-5007');

    expect(screen.getByRole('button', { name: 'Record decisions' })).toBeDisabled();
    await user.type(textarea, ' more');
    expect(screen.queryByTestId('reply-row-TCK-5007')).not.toBeInTheDocument();
  });

  it('shows a 422 from the reply check', async () => {
    mockFetch(
      defaultRoutes({
        'POST /approvals/reply/preview': () =>
          jsonResponse({ detail: 'The reply does not contain any ticket IDs (like TCK-5007).' }, 422),
      }),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.type(screen.getByLabelText("Paste the manager's reply here"), 'Approve all');
    await user.click(screen.getByRole('button', { name: 'Check reply' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('does not contain any ticket IDs');
    expect(screen.getByRole('button', { name: 'Record decisions' })).toBeDisabled();
  });

  it('filters the table to tickets needing attention', async () => {
    mockFetch(defaultRoutes());
    const user = userEvent.setup();
    await renderLoaded();

    expect(
      screen.getByRole('heading', { name: 'All tickets (120 total, 79 open)' }),
    ).toBeInTheDocument();
    const row = screen.getByTestId('dashboard-row-TCK-5007');
    expect(row).toHaveTextContent('05/10/2026 13:05');
    expect(row).toHaveTextContent('Open in_progress');
    expect(row).toHaveTextContent('Refund over 200');
    expect(screen.getByTestId('dashboard-row-TCK-5043')).toHaveTextContent('Resolved resolved');
    expect(screen.getByTestId('dashboard-row-TCK-5084')).toHaveTextContent('—');

    await user.click(screen.getByRole('checkbox', { name: /only tickets needing attention/i }));

    expect(screen.getByTestId('dashboard-row-TCK-5007')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-row-TCK-5084')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-row-TCK-5043')).not.toBeInTheDocument();
  });

  it.each([
    [409, 'No urgent open tickets need a decision, so no email was sent.'],
    [502, 'Approval email could not be sent.'],
    [503, 'Email approval is not configured: SMTP_HOST is not set.'],
  ])('shows the backend error for a %i from send', async (status, detail) => {
    const spy = mockFetch(
      defaultRoutes({
        'POST /approvals/batch/send': () => jsonResponse({ detail }, status),
      }),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Send to manager for approval' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(detail);
    // Nothing was sent, so the dashboard is not reloaded.
    expect(calls(spy, 'GET /dashboard')).toHaveLength(1);
  });

  it('shows a retryable error when the dashboard cannot load', async () => {
    mockFetch(
      defaultRoutes({
        'GET /dashboard': () => jsonResponse({ detail: 'boom' }, 500),
      }),
    );
    render(<EscalationDashboard />);

    expect(await screen.findByRole('alert')).toHaveTextContent('boom');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('formats created dates as DD/MM/YYYY HH:MM', () => {
    expect(formatCreated('2026-10-05 13:05')).toBe('05/10/2026 13:05');
    expect(formatCreated('unknown')).toBe('unknown');
  });
});
