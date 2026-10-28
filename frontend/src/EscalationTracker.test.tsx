import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import App from './App';
import { EscalationTracker } from './components/EscalationTracker';
import { formatHours } from './components/UrgentTicketTable';
import { getApiBaseUrl } from './services/triageApi';
import { UrgentOpenAnalysis, UrgentTicket } from './types/escalation';

// Follow VITE_API_BASE_URL (for example from frontend/.env) like the app does.
const BASE_URL = getApiBaseUrl();

function ticket(overrides: Partial<UrgentTicket>): UrgentTicket {
  return {
    ticket_id: 'TCK-0000',
    category: 'Billing',
    priority: 'urgent',
    created_at: '2026-10-05 13:05',
    status: 'open',
    is_open: true,
    assigned_to: 'riya',
    escalation: null,
    approval_stage: 'not_requested',
    age_hours: 421.1,
    waiting_for_decision_hours: null,
    ...overrides,
  };
}

const pendingEscalation = {
  in_tracker: true,
  request_source: 'tracker' as const,
  requested_by: 'Zoe',
  approver: 'Joyce',
  requested_at: '2026-10-05 23:05',
  tracker_decision_raw: 'Need more info',
  decision: null,
  decided_by: null,
  decided_at: null,
  decision_source: null,
  state: 'pending' as const,
  notes: null,
};

// Counts deliberately differ from the number of rows to prove the summary
// comes from the API's by_stage, not from counting the table.
function analysis(overrides: Partial<UrgentOpenAnalysis> = {}): UrgentOpenAnalysis {
  return {
    total: 7,
    needs_action: 5,
    by_stage: { not_requested: 3, awaiting_decision: 2, accepted: 1, rejected: 1 },
    by_category: { Billing: 4, Shipping: 3 },
    managers: ['Anil', 'Joyce'],
    tickets: [
      ticket({ ticket_id: 'TCK-5110', category: 'Billing', assigned_to: null }),
      ticket({
        ticket_id: 'TCK-5007',
        category: 'Shipping',
        status: 'in_progress',
        approval_stage: 'awaiting_decision',
        escalation: pendingEscalation,
        age_hours: 5.4,
        waiting_for_decision_hours: 50,
      }),
      ticket({
        ticket_id: 'TCK-5003',
        approval_stage: 'accepted',
        escalation: { ...pendingEscalation, decision: 'Accept', state: 'accepted' },
      }),
    ],
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

// Routes GET requests to `onGet` and POST requests to `onPost`.
function mockFetch(onGet: Handler, onPost?: Handler) {
  return vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST') {
        if (!onPost) {
          throw new Error(`Unexpected POST ${url}`);
        }
        return onPost(url, init);
      }
      return onGet(url, init);
    });
}

function getCalls(spy: ReturnType<typeof mockFetch>) {
  return spy.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method !== 'POST');
}

function postCalls(spy: ReturnType<typeof mockFetch>) {
  return spy.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST');
}

async function renderLoaded() {
  render(<EscalationTracker />);
  await screen.findByTestId('ticket-row-TCK-5110');
}

describe('Escalation Tracker', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = '';
  });

  it('opens from the navigation and keeps the triage page as the default', async () => {
    const fetchSpy = mockFetch(() => jsonResponse(analysis()));
    const user = userEvent.setup();
    render(<App />);

    expect(
      screen.getByRole('heading', { level: 1, name: /ai ticket triage/i }),
    ).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole('link', { name: /escalation tracker/i }));

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Escalation Tracker' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /escalation tracker/i })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await screen.findByTestId('ticket-row-TCK-5110');
    expect(fetchSpy).toHaveBeenCalledWith(`${BASE_URL}/approvals/urgent-open`, undefined);
  });

  it('shows a loading indicator, then summary counts from the API', async () => {
    mockFetch(() => jsonResponse(analysis()));
    render(<EscalationTracker />);

    expect(screen.getByText(/loading urgent open tickets/i)).toBeInTheDocument();

    await screen.findByTestId('ticket-row-TCK-5110');
    expect(screen.queryByText(/loading urgent open tickets/i)).not.toBeInTheDocument();
    expect(screen.getByTestId('stat-total')).toHaveTextContent('7');
    expect(screen.getByTestId('stat-not-requested')).toHaveTextContent('3');
    expect(screen.getByTestId('stat-awaiting')).toHaveTextContent('2');
    expect(screen.getByTestId('stat-accepted')).toHaveTextContent('1');
    expect(screen.getByTestId('stat-rejected')).toHaveTextContent('1');
  });

  it('renders ticket details and only the actions that apply to each stage', async () => {
    mockFetch(() => jsonResponse(analysis()));
    await renderLoaded();

    const notRequested = screen.getByTestId('ticket-row-TCK-5110');
    expect(notRequested).toHaveTextContent('Billing');
    expect(notRequested).toHaveTextContent(/urgent/i);
    expect(notRequested).toHaveTextContent('Open');
    expect(notRequested).toHaveTextContent('Unassigned');
    expect(notRequested).toHaveTextContent('Not requested');
    expect(notRequested).toHaveTextContent('17d 13h');
    expect(
      within(notRequested).getByRole('button', { name: /request approval for tck-5110/i }),
    ).toBeInTheDocument();
    expect(within(notRequested).queryByRole('button', { name: /accept/i })).toBeNull();

    const awaiting = screen.getByTestId('ticket-row-TCK-5007');
    expect(awaiting).toHaveTextContent('In progress');
    expect(awaiting).toHaveTextContent('riya');
    expect(awaiting).toHaveTextContent('Awaiting decision');
    expect(awaiting).toHaveTextContent('Approver: Joyce');
    expect(awaiting).toHaveTextContent('5h');
    expect(awaiting).toHaveTextContent('2d 2h');
    expect(within(awaiting).getByRole('button', { name: 'Accept TCK-5007' })).toBeInTheDocument();
    expect(within(awaiting).getByRole('button', { name: 'Reject TCK-5007' })).toBeInTheDocument();
    expect(within(awaiting).queryByRole('button', { name: /request approval/i })).toBeNull();

    const accepted = screen.getByTestId('ticket-row-TCK-5003');
    expect(accepted).toHaveTextContent('No action needed');
    expect(within(accepted).queryByRole('button')).toBeNull();
  });

  it('sends the category and status filters as API query parameters', async () => {
    const fetchSpy = mockFetch(() => jsonResponse(analysis()));
    const user = userEvent.setup();
    await renderLoaded();

    await user.selectOptions(screen.getByLabelText('Category'), 'Shipping');
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenLastCalledWith(
        `${BASE_URL}/approvals/urgent-open?category=Shipping`,
        undefined,
      ),
    );

    await user.selectOptions(screen.getByLabelText('Status'), 'in_progress');
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenLastCalledWith(
        `${BASE_URL}/approvals/urgent-open?category=Shipping&status=in_progress`,
        undefined,
      ),
    );
    expect(screen.getByText(/matching current filters/i)).toBeInTheDocument();
  });

  it('shows an empty state when no tickets match the filters', async () => {
    mockFetch((url) =>
      url.includes('category=')
        ? jsonResponse(
            analysis({
              total: 0,
              needs_action: 0,
              by_stage: { not_requested: 0, awaiting_decision: 0, accepted: 0, rejected: 0 },
              by_category: {},
              tickets: [],
            }),
          )
        : jsonResponse(analysis()),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.selectOptions(screen.getByLabelText('Category'), 'Shipping');

    expect(
      await screen.findByText(/no urgent open tickets match these filters/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId('stat-total')).toHaveTextContent('0');

    await user.click(screen.getByRole('button', { name: /show all urgent open tickets/i }));
    expect(await screen.findByTestId('ticket-row-TCK-5110')).toBeInTheDocument();
  });

  it('shows the error and retries when the API cannot be loaded', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(jsonResponse(analysis()));
    const user = userEvent.setup();
    render(<EscalationTracker />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /unable to connect to the backend server/i,
    );

    await user.click(screen.getByRole('button', { name: /retry/i }));

    expect(await screen.findByTestId('ticket-row-TCK-5110')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('rejects a malformed analysis response without crashing', async () => {
    mockFetch(() => jsonResponse({ tickets: 'nope' }));
    render(<EscalationTracker />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/malformed response/i);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('requests approval with the backend JSON format and refreshes the list', async () => {
    let requested = false;
    const fetchSpy = mockFetch(
      () =>
        jsonResponse(
          requested
            ? analysis({
                by_stage: { not_requested: 2, awaiting_decision: 3, accepted: 1, rejected: 1 },
                tickets: [
                  ticket({
                    ticket_id: 'TCK-5110',
                    approval_stage: 'awaiting_decision',
                    escalation: { ...pendingEscalation, approver: 'Anil' },
                    waiting_for_decision_hours: 0,
                  }),
                ],
              })
            : analysis(),
        ),
      () => {
        requested = true;
        return jsonResponse({ ticket_id: 'TCK-5110' });
      },
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: /request approval for tck-5110/i }));
    const form = screen.getByRole('form', { name: /request approval for tck-5110/i });

    // The manager list comes from the API response.
    const managerSelect = within(form).getByLabelText(/manager/i);
    expect(
      within(managerSelect).getAllByRole('option').map((o) => o.textContent),
    ).toEqual(['Select a manager', 'Anil', 'Joyce']);

    // Blank input is rejected without calling the API.
    await user.type(within(form).getByLabelText(/your name/i), '   ');
    await user.click(within(form).getByRole('button', { name: /submit request/i }));
    expect(within(form).getByText(/your name is required/i)).toBeInTheDocument();
    expect(within(form).getByText(/select the manager/i)).toBeInTheDocument();
    expect(postCalls(fetchSpy)).toHaveLength(0);

    await user.clear(within(form).getByLabelText(/your name/i));
    await user.type(within(form).getByLabelText(/your name/i), '  Lia ');
    await user.selectOptions(managerSelect, 'Anil');
    await user.click(within(form).getByRole('button', { name: /submit request/i }));

    const success = await screen.findByText(/approval request for tck-5110 recorded/i);
    expect(success.closest('[role="status"]')).not.toBeNull();
    expect(success).toHaveTextContent(/with anil as approver/i);
    expect(success).toHaveTextContent(/no email is sent/i);

    const [[url, init]] = postCalls(fetchSpy);
    expect(url).toBe(`${BASE_URL}/approvals/TCK-5110/request`);
    expect((init as RequestInit).headers).toEqual({ 'Content-Type': 'application/json' });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      requested_by: 'Lia',
      approver: 'Anil',
    });

    // The data is reloaded and the updated stage is shown.
    await waitFor(() => expect(getCalls(fetchSpy)).toHaveLength(2));
    await waitFor(() =>
      expect(screen.getByTestId('ticket-row-TCK-5110')).toHaveTextContent('Awaiting decision'),
    );
    expect(screen.getByTestId('stat-awaiting')).toHaveTextContent('3');
    expect(screen.queryByRole('form')).not.toBeInTheDocument();
  });

  it('keeps the form open and shows the backend error when a request fails', async () => {
    const fetchSpy = mockFetch(
      () => jsonResponse(analysis()),
      () => jsonResponse({ detail: 'approval has already been requested for this ticket' }, 409),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: /request approval for tck-5110/i }));
    const form = screen.getByRole('form', { name: /request approval for tck-5110/i });
    await user.type(within(form).getByLabelText(/your name/i), 'Lia');
    await user.selectOptions(within(form).getByLabelText(/manager/i), 'Joyce');
    await user.click(within(form).getByRole('button', { name: /submit request/i }));

    expect(await within(form).findByRole('alert')).toHaveTextContent(
      'approval has already been requested for this ticket',
    );
    expect(within(form).getByRole('button', { name: /submit request/i })).toBeEnabled();
    expect(getCalls(fetchSpy)).toHaveLength(1);

    await user.click(within(form).getByRole('button', { name: /cancel/i }));
    expect(screen.queryByRole('form')).not.toBeInTheDocument();
  });

  it('records an Accept decision after validating the decision-maker name', async () => {
    let decided = false;
    const fetchSpy = mockFetch(
      () =>
        jsonResponse(
          decided
            ? analysis({
                by_stage: { not_requested: 3, awaiting_decision: 1, accepted: 2, rejected: 1 },
                tickets: [
                  ticket({
                    ticket_id: 'TCK-5110',
                  }),
                  ticket({
                    ticket_id: 'TCK-5007',
                    approval_stage: 'accepted',
                    escalation: { ...pendingEscalation, decision: 'Accept', state: 'accepted' },
                  }),
                ],
              })
            : analysis(),
        ),
      () => {
        decided = true;
        return jsonResponse({ ticket_id: 'TCK-5007' });
      },
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Accept TCK-5007' }));
    const form = screen.getByRole('form', { name: /record accept decision for tck-5007/i });
    expect(form).toHaveTextContent('Approval was requested from Joyce.');

    await user.click(within(form).getByRole('button', { name: /confirm accept/i }));
    expect(within(form).getByRole('alert')).toHaveTextContent(
      /decision-maker name is required/i,
    );
    expect(postCalls(fetchSpy)).toHaveLength(0);

    await user.type(within(form).getByLabelText(/decision made by/i), 'Joyce');
    await user.click(within(form).getByRole('button', { name: /confirm accept/i }));

    await waitFor(() =>
      expect(screen.getByTestId('ticket-row-TCK-5007')).toHaveTextContent('Accepted'),
    );
    expect(
      screen.getByText(/accept decision for tck-5007 recorded by joyce/i),
    ).toBeInTheDocument();

    const [[url, init]] = postCalls(fetchSpy);
    expect(url).toBe(`${BASE_URL}/escalations/TCK-5007/decision`);
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      decision: 'Accept',
      decided_by: 'Joyce',
    });
    expect(getCalls(fetchSpy)).toHaveLength(2);
    expect(screen.getByTestId('stat-accepted')).toHaveTextContent('2');
  });

  it('sends Reject when the Reject action is used', async () => {
    const fetchSpy = mockFetch(
      () => jsonResponse(analysis()),
      () => jsonResponse({ ticket_id: 'TCK-5007' }),
    );
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole('button', { name: 'Reject TCK-5007' }));
    const form = screen.getByRole('form', { name: /record reject decision for tck-5007/i });
    await user.type(within(form).getByLabelText(/decision made by/i), 'Anil');
    await user.click(within(form).getByRole('button', { name: /confirm reject/i }));

    await waitFor(() => expect(postCalls(fetchSpy)).toHaveLength(1));
    const [[, init]] = postCalls(fetchSpy);
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      decision: 'Reject',
      decided_by: 'Anil',
    });
  });
});

describe('formatHours', () => {
  it('formats hours as days and hours', () => {
    expect(formatHours(null)).toBe('—');
    expect(formatHours(0.2)).toBe('< 1h');
    expect(formatHours(5.4)).toBe('5h');
    expect(formatHours(24)).toBe('1d 0h');
    expect(formatHours(421.1)).toBe('17d 13h');
  });
});
