import { useEffect, useState } from 'react';
import { TicketForm } from './components/TicketForm';
import { LoadingIndicator } from './components/LoadingIndicator';
import { TriageResult } from './components/TriageResult';
import { EscalationTracker } from './components/EscalationTracker';
import { EscalationDashboard } from './components/EscalationDashboard';
import { submitTriage, ApiError } from './services/triageApi';
import { TriageRequest, TriageResult as TriageResultType } from './types/triage';
import './App.css';

type View = 'triage' | 'escalations' | 'dashboard';

const ESCALATIONS_HASH = '#/escalations';
const DASHBOARD_HASH = '#/dashboard';

const VIEWS: Record<View, { title: string; description: string; footer: string; href: string }> = {
  triage: {
    title: 'AI Ticket Triage',
    description:
      'AI-assisted ticket classification and help-article retrieval. Submit customer support tickets ' +
      'to automatically determine categories, calculate priority, and locate relevant knowledge-base articles.',
    footer: 'AI Ticket Triage System • Task 4',
    href: '#/',
  },
  escalations: {
    title: 'Escalation Tracker',
    description:
      'Urgent tickets that are still open, and where each one is in manager approval. Request approval ' +
      'for tickets not yet sent, and record Accept or Reject decisions for tickets awaiting one.',
    footer: 'Escalation Tracker • Task 5',
    href: ESCALATIONS_HASH,
  },
  dashboard: {
    title: 'Escalation Dashboard',
    description:
      'Send the urgent open tickets that need a decision to the manager in one email, then paste ' +
      'their reply to record the approvals.',
    footer: 'Escalation Dashboard • Task 5',
    href: DASHBOARD_HASH,
  },
};

function viewFromHash(hash: string): View {
  if (hash === ESCALATIONS_HASH) {
    return 'escalations';
  }
  return hash === DASHBOARD_HASH ? 'dashboard' : 'triage';
}

export function App() {
  const [view, setView] = useState<View>(() => viewFromHash(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setView(viewFromHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    document.title = VIEWS[view].title;
  }, [view]);

  const current = VIEWS[view];

  return (
    <div className={`app-container ${view !== 'triage' ? 'app-container-wide' : ''}`}>
      <nav className="app-nav" aria-label="Main">
        {(Object.keys(VIEWS) as View[]).map((key) => (
          <a
            key={key}
            href={VIEWS[key].href}
            className={`app-nav-link ${view === key ? 'active' : ''}`}
            aria-current={view === key ? 'page' : undefined}
          >
            {VIEWS[key].title}
          </a>
        ))}
      </nav>

      <header className="app-header">
        <div className="header-content">
          <h1>{current.title}</h1>
          <p className="app-description">{current.description}</p>
        </div>
      </header>

      <main className="app-main">
        {view === 'triage' && <TriageView />}
        {view === 'escalations' && <EscalationTracker />}
        {view === 'dashboard' && <EscalationDashboard />}
      </main>

      <footer className="app-footer">
        <p>{current.footer}</p>
      </footer>
    </div>
  );
}

function TriageView() {
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<TriageResultType | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (requestData: TriageRequest) => {
    setIsLoading(true);
    setErrorMessage(null);
    setResult(null);

    try {
      const data = await submitTriage(requestData);
      setResult(data);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(err.userMessage);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('An unexpected error occurred while processing the ticket.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setIsLoading(false);
    setResult(null);
    setErrorMessage(null);
  };

  return (
    <>
      {errorMessage && (
        <div className="error-banner" role="alert" aria-live="assertive">
          <div className="error-icon" aria-hidden="true">⚠️</div>
          <div className="error-content">
            <strong>Error</strong>
            <p>{errorMessage}</p>
          </div>
          <button
            type="button"
            className="error-dismiss-btn"
            onClick={() => setErrorMessage(null)}
            aria-label="Dismiss error message"
          >
            ×
          </button>
        </div>
      )}

      <section className="form-section" aria-labelledby="submit-ticket-heading">
        <h2 id="submit-ticket-heading" className="sr-only">Submit Ticket</h2>
        <TicketForm
          isLoading={isLoading}
          onSubmit={handleSubmit}
          onReset={handleReset}
        />
      </section>

      {isLoading && <LoadingIndicator />}

      {result && !isLoading && <TriageResult result={result} />}
    </>
  );
}

export default App;

