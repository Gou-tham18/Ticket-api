import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import App from './App';
import { AUTO_REFRESH_MS, EscalationDashboard } from './components/EscalationDashboard';
import { formatCreated, formatDay } from './components/DashboardTicketTable';
import { getApiBaseUrl } from './services/triageApi';
import {
  ApprovalConfig,
  BatchTicket,
  Dashboard,
  DashboardTicket,
  RecentDecision,
  WaitingTicket,
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
    decision: null,
    decided_by: null,
    decided_at: null,
    decision_source: null,
    ...overrides,
  };
}

function batchTicket(overrides: Partial<BatchTicket>): BatchTicket {
  return {
    ...ticket({ priority: 'urgent', indicators: ['urgent_open'] }),
    approval_stage: 'not_requested',
    summary_line: 'TCK-0000 | Billing | urgent | created 05/10/2026 13:05',
    send_reason: 'new',
    last_emailed_at: null,
    first_requested_at: null,
    days_waiting: null,
    ...overrides,
  };
}

const BATCH = [
  batchTicket({
    ticket_id: 'TCK-5110',
    summary_line:
      'TCK-5110 | Billing | urgent | created 11/10/2026 14:15 | open | assigned to lia | labels escalated, vip | refund 199.00',
  }),
  batchTicket({
    ticket_id: 'TCK-5007',
    approval_stage: 'awaiting_decision',
    send_reason: 'reminder',
    last_emailed_at: '2026-10-05 23:05',
    first_requested_at: '2026-10-05 23:05',
    days_waiting: 14,
    summary_line:
      'TCK-5007 | Refunds | urgent | created 05/10/2026 13:05 | in_progress | assigned to riya | labels escalated | refund 480.00',
  }),
];

const WAITING: WaitingTicket[] = [
  {
    ticket_id: 'TCK-5050',
    category: 'Refunds',
    summary_line: 'TCK-5050 | Refunds | urgent | created 12/10/2026 06:16',
    last_emailed_at: '2026-10-30 09:15',
    reminder_due_at: '2026-10-31 09:15',
  },
];

const DECISIONS: RecentDecision[] = [
  { ticket_id: 'TCK-5070', category: 'Shipping', decision: 'Reject', decided_by: 'Ajith', decided_at: '2026-10-30 10:39' },
  { ticket_id: 'TCK-5106', category: 'Billing', decision: 'Accept', decided_by: 'Ajith', decided_at: '2026-10-29 08:00' },
];

// Counts deliberately differ from the rows to prove they come from the API.
// Rows are in the API's order: open first, then resolved.
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
      ticket({ ticket_id: 'TCK-5084', category: 'Login', created_at: '2026-10-05 13:21' }),
      ticket({
        ticket_id: 'TCK-5106',
        created_at: '2026-10-06 07:42',
        priority: 'urgent',
        indicators: ['urgent_open'],
        approval_stage: 'accepted',
        decision: 'Accept',
        decided_by: 'Ajith',
        decided_at: '2026-10-29 08:00',
        decision_source: 'prototype',
      }),
      ticket({
        ticket_id: 'TCK-5110',
        created_at: '2026-10-11 14:15',
        priority: 'urgent',
        indicators: ['urgent_open'],
        approval_stage: 'not_requested',
      }),
      ticket({ ticket_id: 'TCK-5043', status: 'resolved', is_open: false }),
      ticket({
        ticket_id: 'TCK-5039',
        status: 'resolved',
        is_open: false,
        created_at: '2026-10-05 21:10',
        approval_stage: 'rejected',
        decision: 'Reject',
        decided_by: 'Anil',
        decided_at: '2026-10-06 04:10',
        decision_source: 'tracker',
      }),
    ],
    approval_batch: { count: 2, fields_saved: 16, tickets: BATCH },
    reminder_days: 1,
    link_days: 7,
    waiting_for_reply: WAITING,
    next_reminder_due_at: '2026-10-31 09:15',
    recent_decisions: DECISIONS,
    ...overrides,
  };
}

const EMPTY_BATCH = { count: 0, fields_saved: 0, tickets: [] };

const CONFIG: ApprovalConfig = {
  user_name: 'Riya',
  manager_name: 'Mara',
  configured: true,
  email_configured: true,
  buttons_configured: true,
  buttons_missing: [],
};

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

type Routes = Record<string, () => Response | Promise<Response>>;

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

function rowIds(): string[] {
  return screen
    .getAllByTestId(/^dashboard-row-/)
    .map((row) => row.getAttribute('data-testid')!.replace('dashboard-row-', ''));
}

let visibility: DocumentVisibilityState = 'visible';

function setVisibility(state: DocumentVisibilityState) {
  visibility = state;
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('Escalation Dashboard', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    visibility = 'visible';
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => visibility,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
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
    expect(screen.queryByTestId('buttons-warning')).not.toBeInTheDocument();
    expect(screen.getByText(/sensitive details/i)).toBeInTheDocument();
    expect(screen.getByTestId('attention-urgent_open')).toHaveTextContent('Urgent & open10');
    expect(screen.getByTestId('attention-escalated_label')).toHaveTextContent('23');
    expect(screen.getByTestId('attention-refund_over_200')).toHaveTextContent('7');
    expect(screen.getByTestId('attention-sentence')).toHaveTextContent(
      '25 open tickets match at least one condition.',
    );
    expect(screen.getByText(/for information only/i)).toBeInTheDocument();
  });

  it('has no paste-reply section any more', async () => {
    const spy = mockFetch(defaultRoutes());
    await renderLoaded();

    expect(screen.queryByText(/record manager's reply/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check reply' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record decisions' })).not.toBeInTheDocument();
    expect(spy.mock.calls.some(([input]) => String(input).includes('/approvals/reply'))).toBe(
      false,
    );
  });

  it('lists the batch with New and Reminder badges and the fields-saved line', async () => {
    mockFetch(defaultRoutes());
    await renderLoaded();

    const list = screen.getByRole('list', { name: /next approval email/i });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(list).toHaveTextContent(BATCH[1].summary_line);
    expect(screen.getByTestId('batch-line-TCK-5110')).toHaveTextContent('New');
    expect(screen.getByTestId('batch-line-TCK-5007')).toHaveTextContent(
      'Reminder · waiting 14 days',
    );
    expect(screen.getByTestId('fields-saved')).toHaveTextContent(
      "2 escalations prepared automatically: 16 ticket fields that didn't need to be copied by hand (2 tickets × 8 fields)",
    );
    expect(screen.getByRole('button', { name: 'Send to manager for approval' })).toBeEnabled();
  });

  it('shows the tickets waiting for the manager', async () => {
    mockFetch(defaultRoutes());
    await renderLoaded();

    const list = screen.getByRole('list', { name: /waiting for the manager's reply/i });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByTestId('waiting-line-TCK-5050')).toHaveTextContent(
      'Emailed 30/10/2026 09:15 · comes back 31/10/2026 09:15 if no decision',
    );
  });

  it('hides the waiting list when nothing is waiting', async () => {
    mockFetch(
      defaultRoutes({
        'GET /dashboard': () =>
          jsonResponse(dashboard({ waiting_for_reply: [], next_reminder_due_at: null })),
      }),
    );
    await renderLoaded();

    expect(
      screen.queryByRole('list', { name: /waiting for the manager's reply/i }),
    ).not.toBeInTheDocument();
  });

  it('says when the next reminder is due if nothing is ready but tickets wait', async () => {
    mockFetch(
      defaultRoutes({
        'GET /dashboard': () => jsonResponse(dashboard({ approval_batch: EMPTY_BATCH })),
      }),
    );
    await renderLoaded();

    expect(screen.getByTestId('batch-empty')).toHaveTextContent(
      "Nothing to send right now. 1 ticket is waiting for the manager's decision. The next reminder is due 31/10/2026 09:15.",
    );
    expect(screen.getByRole('button', { name: 'Send to manager for approval' })).toBeDisabled();
    expect(screen.queryByTestId('fields-saved')).not.toBeInTheDocument();
  });

  it('disables sending when nothing is ready or waiting', async () => {
    mockFetch(
      defaultRoutes({
        'GET /dashboard': () =>
          jsonResponse(
            dashboard({
              approval_batch: EMPTY_BATCH,
              waiting_for_reply: [],
              next_reminder_due_at: null,
            }),
          ),
      }),
    );
    await renderLoaded();

    expect(screen.getByTestId('batch-empty')).toHaveTextContent(
      'No urgent open tickets need a decision.',
    );
    expect(screen.getByRole('button', { name: 'Send to manager for approval' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Preview email' })).toBeDisabled();
  });

  it('warns about missing button settings in plain words and disables Send', async () => {
    mockFetch(
      defaultRoutes({
        'GET /approvals/config': () =>
          jsonResponse({
            ...CONFIG,
            email_configured: false,
            buttons_configured: false,
            buttons_missing: ['PUBLIC_BASE_URL', 'APPROVAL_LINK_SECRET'],
          }),
      }),
    );
    await renderLoaded();

    const warning = await screen.findByTestId('buttons-warning');
    expect(warning).toHaveTextContent(
      'Add the public web address (PUBLIC_BASE_URL) and the link secret (APPROVAL_LINK_SECRET)',
    );
    expect(screen.getByTestId('sending-as')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send to manager for approval' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Preview email' })).toBeDisabled();
  });

  it('names only the missing button setting', async () => {
    mockFetch(
      defaultRoutes({
        'GET /approvals/config': () =>
          jsonResponse({
            ...CONFIG,
            email_configured: false,
            buttons_configured: false,
            buttons_missing: ['APPROVAL_LINK_SECRET'],
          }),
      }),
    );
    await renderLoaded();

    const warning = await screen.findByTestId('buttons-warning');
    expect(warning).toHaveTextContent('the link secret (APPROVAL_LINK_SECRET)');
    expect(warning).not.toHaveTextContent('PUBLIC_BASE_URL');
  });

  it('previews the HTML email in a sandboxed iframe', async () => {
    const html = '<p>Hi Mara,</p><a href="https://x.example/approvals/respond?token=a.b">Approve</a>';
    mockFetch(
      defaultRoutes({
        'GET /approvals/batch/preview': () =>
          jsonResponse({
            to: 'Mara',
            from: 'Riya',
            subject: 'Urgent tickets awaiting your approval (2, including 1 reminder)',
            body: 'Hi Mara,\n',
            text_body: 'Hi Mara,\n',
            html_body: html,
            ticket_ids: ['TCK-5110', 'TCK-5007'],
          }),
      }),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Preview email' }));

    expect(
      await screen.findByText('Urgent tickets awaiting your approval (2, including 1 reminder)'),
    ).toBeInTheDocument();
    const frame = screen.getByTitle('Approval email preview');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('sandbox', '');
    expect(frame.getAttribute('srcdoc')).toContain(html);
    expect(frame.getAttribute('srcdoc')).toContain('pointer-events:none');
    expect(screen.getByRole('button', { name: 'Hide email preview' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('sends the batch, names new tickets and reminders, and reloads', async () => {
    const spy = mockFetch(
      defaultRoutes({
        'POST /approvals/batch/send': () =>
          jsonResponse({
            sent: true,
            ticket_ids: ['TCK-5110', 'TCK-5007'],
            newly_requested: ['TCK-5110'],
            reminders: ['TCK-5007'],
            next_reminder_due_at: '2026-10-31 09:15',
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

  it('warns and disables send when the user and manager are not configured', async () => {
    mockFetch(
      defaultRoutes({
        'GET /approvals/config': () =>
          jsonResponse({
            user_name: null,
            manager_name: null,
            configured: false,
            email_configured: false,
            buttons_configured: true,
            buttons_missing: [],
          }),
      }),
    );
    await renderLoaded();

    expect(await screen.findByText(/not configured on the backend/i)).toBeInTheDocument();
    expect(screen.queryByTestId('sending-as')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send to manager for approval' })).toBeDisabled();
  });

  it('shows the manager decisions table', async () => {
    mockFetch(defaultRoutes());
    await renderLoaded();

    const table = screen.getByRole('table', { name: /decisions recorded/i });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('TCK-5070ShippingRejectedAjith30/10/2026 10:39');
    expect(screen.getByTestId('decision-row-TCK-5106')).toHaveTextContent(
      'TCK-5106BillingAcceptedAjith29/10/2026 08:00',
    );
  });

  it('shows an empty state when no decisions are recorded', async () => {
    mockFetch(
      defaultRoutes({
        'GET /dashboard': () => jsonResponse(dashboard({ recent_decisions: [] })),
      }),
    );
    await renderLoaded();

    expect(screen.getByRole('heading', { name: 'Manager decisions' })).toBeInTheDocument();
    expect(screen.getByText('No decisions recorded yet.')).toBeInTheDocument();
  });

  it('shows the approval column for each ticket', async () => {
    mockFetch(defaultRoutes());
    await renderLoaded();

    expect(screen.getByRole('columnheader', { name: 'Approval' })).toBeInTheDocument();
    expect(screen.getByTestId('approval-TCK-5106')).toHaveTextContent('Acceptedby Ajith, 29/10/2026');
    expect(screen.getByTestId('approval-TCK-5039')).toHaveTextContent('Rejectedby Anil, 06/10/2026');
    expect(screen.getByTestId('approval-TCK-5007')).toHaveTextContent('Awaiting decision');
    expect(screen.getByTestId('approval-TCK-5110')).toHaveTextContent('Not requested');
    expect(screen.getByTestId('approval-TCK-5084')).toHaveTextContent('—');
  });

  it('keeps the API order (open first) with and without the filter', async () => {
    mockFetch(defaultRoutes());
    const user = userEvent.setup();
    await renderLoaded();

    expect(
      screen.getByRole('heading', { name: 'All tickets (120 total, 79 open)' }),
    ).toBeInTheDocument();
    expect(rowIds()).toEqual(['TCK-5007', 'TCK-5084', 'TCK-5106', 'TCK-5110', 'TCK-5043', 'TCK-5039']);
    const row = screen.getByTestId('dashboard-row-TCK-5007');
    expect(row).toHaveTextContent('05/10/2026 13:05');
    expect(row).toHaveTextContent('Open in_progress');
    expect(row).toHaveTextContent('Refund over 200');
    expect(screen.getByTestId('dashboard-row-TCK-5043')).toHaveTextContent('Resolved resolved');

    await user.click(screen.getByRole('checkbox', { name: /only tickets needing attention/i }));

    expect(rowIds()).toEqual(['TCK-5007', 'TCK-5106', 'TCK-5110']);
  });

  it('reloads the dashboard and settings with the Refresh button', async () => {
    const spy = mockFetch(defaultRoutes());
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Refresh' }));

    await waitFor(() => expect(calls(spy, 'GET /dashboard')).toHaveLength(2));
    expect(calls(spy, 'GET /approvals/config')).toHaveLength(2);
  });

  it('reloads automatically every minute while visible', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const spy = mockFetch(defaultRoutes());
    await renderLoaded();
    expect(calls(spy, 'GET /dashboard')).toHaveLength(1);

    await act(() => vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS - 1000));
    expect(calls(spy, 'GET /dashboard')).toHaveLength(1);

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(calls(spy, 'GET /dashboard')).toHaveLength(2);

    await act(() => vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS));
    expect(calls(spy, 'GET /dashboard')).toHaveLength(3);
  });

  it('pauses auto-refresh while the tab is hidden and catches up when shown', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const spy = mockFetch(defaultRoutes());
    await renderLoaded();

    act(() => setVisibility('hidden'));
    await act(() => vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS * 3));
    expect(calls(spy, 'GET /dashboard')).toHaveLength(1);

    act(() => setVisibility('visible'));
    await waitFor(() => expect(calls(spy, 'GET /dashboard')).toHaveLength(2));
  });

  it('never auto-refreshes while a send is in progress', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let finishSend: (response: Response) => void = () => {};
    const spy = mockFetch(
      defaultRoutes({
        'POST /approvals/batch/send': () =>
          new Promise<Response>((resolve) => {
            finishSend = resolve;
          }),
      }),
    );
    await renderLoaded();

    fireEvent.click(screen.getByRole('button', { name: 'Send to manager for approval' }));
    expect(await screen.findByRole('button', { name: 'Sending...' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled();

    await act(() => vi.advanceTimersByTimeAsync(AUTO_REFRESH_MS * 2));
    expect(calls(spy, 'GET /dashboard')).toHaveLength(1);

    await act(async () => {
      finishSend(
        jsonResponse({
          sent: true,
          ticket_ids: ['TCK-5110'],
          newly_requested: ['TCK-5110'],
          reminders: [],
          next_reminder_due_at: null,
        }),
      );
    });
    // The reload after a successful send.
    await waitFor(() => expect(calls(spy, 'GET /dashboard')).toHaveLength(2));
  });

  it.each([
    [409, "Nothing to send yet. 1 ticket is waiting for the manager's reply; the next reminder is due 31/10/2026."],
    [502, 'Approval email could not be sent.'],
    [503, 'Email approval is not configured: PUBLIC_BASE_URL is not set.'],
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

  it('rejects a dashboard response without the new fields', async () => {
    const { recent_decisions: _omitted, ...old } = dashboard();
    mockFetch(defaultRoutes({ 'GET /dashboard': () => jsonResponse(old) }));
    render(<EscalationDashboard />);

    expect(await screen.findByRole('alert')).toHaveTextContent('malformed response');
  });

  it('formats dates as DD/MM/YYYY HH:MM and DD/MM/YYYY', () => {
    expect(formatCreated('2026-10-05 13:05')).toBe('05/10/2026 13:05');
    expect(formatCreated('unknown')).toBe('unknown');
    expect(formatDay('2026-10-29 08:00')).toBe('29/10/2026');
  });
});
