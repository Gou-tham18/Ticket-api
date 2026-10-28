import { useState } from 'react';
import { TicketForm } from './components/TicketForm';
import { LoadingIndicator } from './components/LoadingIndicator';
import { TriageResult } from './components/TriageResult';
import { submitTriage, ApiError } from './services/triageApi';
import { TriageRequest, TriageResult as TriageResultType } from './types/triage';
import './App.css';

export function App() {
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
    <div className="app-container">
      <header className="app-header">
        <div className="header-content">
          <h1>AI Ticket Triage</h1>
          <p className="app-description">
            AI-assisted ticket classification and help-article retrieval. Submit customer support tickets
            to automatically determine categories, calculate priority, and locate relevant knowledge-base articles.
          </p>
        </div>
      </header>

      <main className="app-main">
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
      </main>

      <footer className="app-footer">
        <p>AI Ticket Triage System &bull; Task 4</p>
      </footer>
    </div>
  );
}

export default App;

