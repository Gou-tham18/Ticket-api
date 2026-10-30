import React, { useCallback, useEffect, useRef, useState } from 'react';
import { LoadingIndicator } from './LoadingIndicator';
import { ErrorBanner, errorText } from './Banners';
import { ApprovalBatchPanel } from './ApprovalBatchPanel';
import { ReplyRecorder } from './ReplyRecorder';
import { DashboardTicketTable, IndicatorBadge, INDICATOR_LABELS } from './DashboardTicketTable';
import { fetchApprovalConfig, fetchDashboard } from '../services/dashboardApi';
import { ApprovalConfig, Dashboard, Indicator } from '../types/dashboard';

const INDICATORS: Indicator[] = ['urgent_open', 'escalated_label', 'refund_over_200'];

export const EscalationDashboard: React.FC = () => {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [config, setConfig] = useState<ApprovalConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const latestRequest = useRef(0);

  const loadDashboard = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setIsLoading(true);
    setLoadError(null);
    try {
      const data = await fetchDashboard();
      if (requestId === latestRequest.current) {
        setDashboard(data);
      }
    } catch (err: unknown) {
      if (requestId === latestRequest.current) {
        setLoadError(errorText(err, 'Unable to load the dashboard.'));
      }
    } finally {
      if (requestId === latestRequest.current) {
        setIsLoading(false);
      }
    }
  }, []);

  const loadConfig = useCallback(async () => {
    setConfigError(null);
    try {
      setConfig(await fetchApprovalConfig());
    } catch (err: unknown) {
      setConfigError(errorText(err, 'Unable to load the approval settings.'));
    }
  }, []);

  useEffect(() => {
    loadConfig();
    loadDashboard();
  }, [loadConfig, loadDashboard]);

  const configured = Boolean(config?.configured);

  return (
    <>
      <section className="summary-section dashboard-intro" aria-label="About this data">
        <p className="muted-text">
          Data comes from the Help Desk CSV export with sensitive details (customer email)
          removed. It is not live: it changes when a new export is saved.
        </p>
        {config && configured && (
          <p className="sending-as" data-testid="sending-as">
            Sending as <strong>{config.user_name}</strong> → to{' '}
            <strong>{config.manager_name}</strong>
          </p>
        )}
        {config && !configured && (
          <p className="config-warning" role="alert">
            The fixed user and manager are not configured on the backend
            (APPROVAL_USER_NAME and APPROVAL_MANAGER_NAME), so emails cannot be sent and
            replies cannot be recorded.
          </p>
        )}
        {configError && <ErrorBanner message={configError} onRetry={loadConfig} />}
      </section>

      {loadError && (
        <ErrorBanner message={loadError} onRetry={loadDashboard} retryDisabled={isLoading} />
      )}

      {isLoading && !dashboard && <LoadingIndicator message="Loading dashboard..." />}

      {dashboard && (
        <>
          <section className="summary-section" aria-labelledby="attention-heading">
            <h2 id="attention-heading" className="section-title">
              Tickets needing attention (open tickets)
            </h2>
            <dl className="stat-grid">
              {INDICATORS.map((indicator) => (
                <div
                  key={indicator}
                  className={`stat-tile stat-indicator-${indicator}`}
                  data-testid={`attention-${indicator}`}
                >
                  <dt className="stat-label">
                    <IndicatorBadge indicator={indicator} />
                    <span className="sr-only">{INDICATOR_LABELS[indicator]}</span>
                  </dt>
                  <dd className="stat-value">{dashboard.attention[indicator]}</dd>
                </div>
              ))}
            </dl>
            <p className="attention-sentence" data-testid="attention-sentence">
              {dashboard.attention.any_condition} open tickets match at least one condition.
            </p>
            <p className="muted-text">
              Only Urgent &amp; open tickets go to the manager for approval. Escalated label
              and Refund over 200 are for information only.
            </p>
          </section>

          <ApprovalBatchPanel
            batch={dashboard.approval_batch}
            config={config}
            onSent={loadDashboard}
          />

          <ReplyRecorder
            configured={configured}
            managerName={config?.manager_name ?? null}
            onRecorded={loadDashboard}
          />

          <DashboardTicketTable
            tickets={dashboard.tickets}
            totalCount={dashboard.total_tickets}
            openCount={dashboard.open_tickets}
          />
        </>
      )}
    </>
  );
};
