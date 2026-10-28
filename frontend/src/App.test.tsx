import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import App from './App';

describe('AI Ticket Triage Application', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 1. The main page renders
  it('1. renders the main page header and description', () => {
    render(<App />);

    expect(
      screen.getByRole('heading', { level: 1, name: /ai ticket triage/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ai-assisted ticket classification and help-article retrieval/i),
    ).toBeInTheDocument();
  });

  // 2. The form displays subject and message inputs
  it('2. displays subject and description inputs with submit and clear buttons', () => {
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });
    const clearButton = screen.getByRole('button', { name: /clear/i });

    expect(subjectInput).toBeInTheDocument();
    expect(descriptionInput).toBeInTheDocument();
    expect(submitButton).toBeInTheDocument();
    expect(clearButton).toBeInTheDocument();
  });

  // 3. Empty or whitespace-only input is rejected
  it('3. rejects empty or whitespace-only inputs without calling API', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const user = userEvent.setup();

    render(<App />);

    const submitButton = screen.getByRole('button', { name: /submit for triage/i });
    await user.click(submitButton);

    expect(
      screen.getByText(/subject is required and cannot be blank/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ticket description is required and cannot be blank/i),
    ).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();

    // Now test whitespace-only inputs
    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);

    await user.type(subjectInput, '    ');
    await user.type(descriptionInput, '    \n  ');
    await user.click(submitButton);

    expect(
      screen.getByText(/subject is required and cannot be blank/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ticket description is required and cannot be blank/i),
    ).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  // 4. A successful mocked API response renders the result fields
  it('4. renders category, priority, reply, and articles on successful triage', async () => {
    const mockTriageResponse = {
      category: 'Login',
      priority: 'high',
      suggested_reply:
        'Please use the Forgot password option and check your spam folder.',
      article_ids: ['KB-001'],
    };

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockTriageResponse,
    } as Response);

    const user = userEvent.setup();
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });

    await user.type(subjectInput, 'Cannot reset my password');
    await user.type(
      descriptionInput,
      'I have not received the password reset email.',
    );
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByTestId('result-category')).toHaveTextContent('Login');
    });

    expect(screen.getByTestId('result-priority')).toHaveTextContent(/high/i);
    expect(screen.getByTestId('result-suggested-reply')).toHaveTextContent(
      'Please use the Forgot password option and check your spam folder.',
    );
    expect(screen.getByTestId('result-article-ids')).toHaveTextContent('KB-001');
  });

  // 5. The loading state appears during submission
  it('5. displays the loading indicator and disables submit while request is pending', async () => {
    let resolvePromise: (value: Response) => void;
    const pendingPromise = new Promise<Response>((resolve) => {
      resolvePromise = resolve;
    });

    vi.spyOn(globalThis, 'fetch').mockReturnValueOnce(pendingPromise);

    const user = userEvent.setup();
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });

    await user.type(subjectInput, 'Billing question');
    await user.type(descriptionInput, 'I was charged twice.');
    await user.click(submitButton);

    expect(
      screen.getByText(/analyzing ticket and retrieving relevant articles/i),
    ).toBeInTheDocument();
    expect(submitButton).toBeDisabled();

    // Now resolve the promise
    resolvePromise!({
      ok: true,
      status: 200,
      json: async () => ({
        category: 'Billing',
        priority: 'urgent',
        suggested_reply: 'We have processed your refund.',
        article_ids: ['KB-002'],
      }),
    } as Response);

    await waitFor(() => {
      expect(
        screen.queryByText(/analyzing ticket and retrieving relevant articles/i),
      ).not.toBeInTheDocument();
    });

    expect(screen.getByTestId('result-category')).toHaveTextContent('Billing');
    expect(submitButton).toBeEnabled();
  });

  // 6. HTTP 422 errors are handled
  it('6. handles HTTP 422 validation errors gracefully', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          {
            loc: ['body', 'subject'],
            msg: 'String should have at most 500 characters',
          },
        ],
      }),
    } as Response);

    const user = userEvent.setup();
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });

    await user.type(subjectInput, 'Very long subject');
    await user.type(descriptionInput, 'Some valid description text');
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    expect(screen.getByRole('alert')).toHaveTextContent(/validation error on subject/i);
  });

  // 7. HTTP 502 errors are handled
  it('7. handles HTTP 502 model/service errors gracefully', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => ({
        detail: 'Ticket triage service failed.',
      }),
    } as Response);

    const user = userEvent.setup();
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });

    await user.type(subjectInput, 'Cannot log in');
    await user.type(descriptionInput, 'Authentication failure');
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    expect(screen.getByRole('alert')).toHaveTextContent(
      /ticket triage service encountered a server error/i,
    );
  });

  // 8. Network failures display an appropriate message
  it('8. displays friendly message on network failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(
      new TypeError('Failed to fetch'),
    );

    const user = userEvent.setup();
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });

    await user.type(subjectInput, 'Cannot log in');
    await user.type(descriptionInput, 'Authentication failure');
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    expect(screen.getByRole('alert')).toHaveTextContent(
      /unable to connect to the backend server/i,
    );
  });

  // 9. Malformed responses do not crash the interface
  it('9. handles malformed responses without crashing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        unknownField: 'bad data',
      }),
    } as Response);

    const user = userEvent.setup();
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i);
    const descriptionInput = screen.getByLabelText(/ticket description/i);
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });

    await user.type(subjectInput, 'System question');
    await user.type(descriptionInput, 'How do I export my data?');
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    expect(screen.getByRole('alert')).toHaveTextContent(
      /malformed response from the triage service/i,
    );
    expect(screen.queryByTestId('result-category')).not.toBeInTheDocument();
  });

  // 10. Reset clears the form and prior results
  it('10. resets form inputs, errors, and previous results when Clear is clicked', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        category: 'Shipping',
        priority: 'normal',
        suggested_reply: 'Your order has shipped.',
        article_ids: ['KB-003'],
      }),
    } as Response);

    const user = userEvent.setup();
    render(<App />);

    const subjectInput = screen.getByLabelText(/subject/i) as HTMLInputElement;
    const descriptionInput = screen.getByLabelText(
      /ticket description/i,
    ) as HTMLTextAreaElement;
    const submitButton = screen.getByRole('button', { name: /submit for triage/i });
    const clearButton = screen.getByRole('button', { name: /clear/i });

    await user.type(subjectInput, 'Tracking issue');
    await user.type(descriptionInput, 'Where is my parcel?');
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByTestId('result-category')).toHaveTextContent('Shipping');
    });

    // Now click clear
    await user.click(clearButton);

    expect(subjectInput.value).toBe('');
    expect(descriptionInput.value).toBe('');
    expect(screen.queryByTestId('result-category')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
