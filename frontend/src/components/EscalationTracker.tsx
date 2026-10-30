import React, { useCallback, useEffect, useRef, useState } from 'react';
import { LoadingIndicator } from './LoadingIndicator';
import { EscalationSummary } from './EscalationSummary';
import { ActiveAction, UrgentTicketTable } from './UrgentTicketTable';
import {
  fetchUrgentOpen,
  recordDecision,
  requestApproval,
} from '../services/escalationApi';
import {
  ApprovalRequestPayload,
  DecisionPayload,
  OpenStatus,
  UrgentOpenAnalysis,
  UrgentOpenFilters,
} from '../types/escalation';

const STATUS_OPTIONS: { value: OpenStatus; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In progress' },
];

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export const EscalationTracker: React.FC = () => {
  const [filters, setFilters] = useState<UrgentOpenFilters>({});
  const [analysis, setAnalysis] = useState<UrgentOpenAnalysis | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<ActiveAction | null>(null);
  // Categories seen in any response, so the filter keeps offering them
  // after the list has been narrowed to one category.
  const [categories, setCategories] = useState<string[]>([]);

  const latestRequest = useRef(0);
  const successRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (currentFilters: UrgentOpenFilters) => {
    const requestId = ++latestRequest.current;
    setIsLoading(true);
    setLoadError(null);

    try {
      const data = await fetchUrgentOpen(currentFilters);
      // Ignore responses for filters the user has already changed.
      if (requestId !== latestRequest.current) {
        return;
      }
      setAnalysis(data);
      setCategories((prev) => {
        const next = new Set(prev);
        Object.keys(data.by_category).forEach((c) => next.add(c));
        data.tickets.forEach((t) => next.add(t.category));
        return Array.from(next).sort();
      });
    } catch (err: unknown) {
      if (requestId !== latestRequest.current) {
        return;
      }
      setLoadError(errorText(err, 'Unable to load urgent open tickets.'));
    } finally {
      if (requestId === latestRequest.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    load(filters);
  }, [filters, load]);

  useEffect(() => {
    if (successMessage) {
      successRef.current?.focus();
    }
  }, [successMessage]);

  const updateFilter = (changes: Partial<UrgentOpenFilters>) => {
    setActiveAction(null);
    setSuccessMessage(null);
    setFilters((prev) => ({ ...prev, ...changes }));
  };

  const handleRequestApproval = async (
    ticketId: string,
    payload: ApprovalRequestPayload,
  ) => {
    await requestApproval(ticketId, payload);
    setActiveAction(null);
    setSuccessMessage(
      `Approval request for ${ticketId} recorded with ${payload.approver} as approver. ` +
        'No email is sent, so let the manager know.',
    );
    await load(filters);
  };

  const handleRecordDecision = async (ticketId: string, payload: DecisionPayload) => {
    await recordDecision(ticketId, payload);
    setActiveAction(null);
    setSuccessMessage(
      `${payload.decision} decision for ${ticketId} recorded by ${payload.decided_by}.`,
    );
    await load(filters);
  };

  const isFiltered = Boolean(filters.category || filters.status);
  const categoryOptions =
    filters.category && !categories.includes(filters.category)
      ? [...categories, filters.category].sort()
      : categories;

  return (
    <>
      {successMessage && (
        <div
          ref={successRef}
          className="success-banner"
          role="status"
          aria-live="polite"
          tabIndex={-1}
        >
          <div className="success-icon" aria-hidden="true">✓</div>
          <div className="error-content">
            <strong>Saved</strong>
            <p>{successMessage}</p>
          </div>
          <button
            type="button"
            className="error-dismiss-btn success-dismiss-btn"
            onClick={() => setSuccessMessage(null)}
            aria-label="Dismiss success message"
          >
            ×
          </button>
        </div>
      )}

      {loadError && (
        <div className="error-banner" role="alert" aria-live="assertive">
          <div className="error-icon" aria-hidden="true">⚠️</div>
          <div className="error-content">
            <strong>Error</strong>
            <p>{loadError}</p>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={() => load(filters)}
            disabled={isLoading}
          >
            Retry
          </button>
        </div>
      )}

      <section className="filter-section" aria-labelledby="filters-heading">
        <h2 id="filters-heading" className="sr-only">Filters</h2>
        <div className="filter-bar">
          <div className="form-group">
            <label htmlFor="filter-category" className="form-label">
              Category
            </label>
            <select
              id="filter-category"
              className="form-input"
              value={filters.category ?? ''}
              onChange={(e) => updateFilter({ category: e.target.value || undefined })}
            >
              <option value="">All categories</option>
              {categoryOptions.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="filter-status" className="form-label">
              Status
            </label>
            <select
              id="filter-status"
              className="form-input"
              value={filters.status ?? ''}
              onChange={(e) =>
                updateFilter({ status: (e.target.value || undefined) as OpenStatus | undefined })
              }
            >
              <option value="">Open and in progress</option>
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            className="btn btn-secondary filter-refresh"
            onClick={() => load(filters)}
            disabled={isLoading}
          >
            Refresh
          </button>
        </div>
      </section>

      {isLoading && !analysis && (
        <LoadingIndicator message="Loading urgent open tickets..." />
      )}

      {analysis && (
        <>
          <EscalationSummary analysis={analysis} isFiltered={isFiltered} />

          <section
            className="tickets-section"
            aria-labelledby="urgent-tickets-heading"
            aria-busy={isLoading}
          >
            <div className="section-header">
              <h2 id="urgent-tickets-heading" className="section-title">
                Urgent open tickets
              </h2>
              {isLoading && (
                <span className="refresh-status" role="status">
                  <span className="spinner spinner-small" aria-hidden="true" />
                  Refreshing...
                </span>
              )}
            </div>

            {analysis.tickets.length === 0 ? (
              <div className="empty-state">
                <p>
                  {isFiltered
                    ? 'No urgent open tickets match these filters.'
                    : 'There are no urgent open tickets right now.'}
                </p>
                {isFiltered && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-small"
                    onClick={() => updateFilter({ category: undefined, status: undefined })}
                  >
                    Show all urgent open tickets
                  </button>
                )}
              </div>
            ) : (
              <UrgentTicketTable
                tickets={analysis.tickets}
                managers={analysis.managers}
                activeAction={activeAction}
                disabled={isLoading}
                onOpenAction={(action) => {
                  setSuccessMessage(null);
                  setActiveAction(action);
                }}
                onCancelAction={() => setActiveAction(null)}
                onRequestApproval={handleRequestApproval}
                onRecordDecision={handleRecordDecision}
              />
            )}
          </section>
        </>
      )}
    </>
  );
};
