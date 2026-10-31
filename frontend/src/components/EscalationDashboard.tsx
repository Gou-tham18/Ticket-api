import React, { useCallback, useEffect, useRef, useState } from 'react';
import { LoadingIndicator } from './LoadingIndicator';
import { ErrorBanner, errorText } from './Banners';
import { ApprovalBatchPanel } from './ApprovalBatchPanel';
import { ManagerDecisionsTable } from './ManagerDecisionsTable';
import { DashboardTicketTable, IndicatorBadge, INDICATOR_LABELS } from './DashboardTicketTable';
import { fetchApprovalConfig, fetchDashboard } from '../services/dashboardApi';
import { ApprovalConfig, ButtonSetting, Dashboard, Indicator } from '../types/dashboard';

const INDICATORS: Indicator[] = ['urgent_open', 'escalated_label', 'refund_over_200'];

// Decisions made from the email appear without a manual reload.
export const AUTO_REFRESH_MS = 60_000;

const BUTTON_SETTING_WORDS: Record<ButtonSetting, string> = {
  PUBLIC_BASE_URL: 'the public web address (PUBLIC_BASE_URL)',
  APPROVAL_LINK_SECRET: 'the link secret (APPROVAL_LINK_SECRET)',
};

function isPageHidden(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

export const EscalationDashboard: React.FC = () => {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [config, setConfig] = useState<ApprovalConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const latestRequest = useRef(0);
  // Read by the auto-refresh timer, which must not reload during a send.
  const isSendingRef = useRef(false);
  const missedWhileHidden = useRef(false);

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

  // Reload every minute while the tab is visible. A tick missed while hidden
  // is caught up as soon as the tab is shown again.
  useEffect(() => {
    const autoRefresh = () => {
      if (isSendingRef.current) {
        return;
      }
      if (isPageHidden()) {
        missedWhileHidden.current = true;
        return;
      }
      loadDashboard();
    };
    const onVisibilityChange = () => {
      if (!isPageHidden() && missedWhileHidden.current) {
        missedWhileHidden.current = false;
        autoRefresh();
      }
    };
    const timer = window.setInterval(autoRefresh, AUTO_REFRESH_MS);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [loadDashboard]);

  const handleSendingChange = useCallback((sending: boolean) => {
    isSendingRef.current = sending;
    setIsSending(sending);
  }, []);

  const handleRefresh = () => {
    loadConfig();
    loadDashboard();
  };

  const configured = Boolean(config?.configured);
  const buttonsMissing = config && !config.buttons_configured ? config.buttons_missing : [];

  return (
    <>
      <section className="summary-section dashboard-intro" aria-label="About this data">
        <div className="dashboard-intro-row">
          <p className="muted-text">
            Data comes from the Help Desk CSV export with sensitive details (customer email)
            removed. It is not live: it changes when a new export is saved. Decisions made
            from the email appear here within a minute.
          </p>
          <button
            type="button"
            className="btn btn-secondary btn-small"
            onClick={handleRefresh}
            disabled={isLoading || isSending}
            aria-busy={isLoading}
          >
            Refresh
          </button>
        </div>
        {config && configured && (
          <p className="sending-as" data-testid="sending-as">
            Sending as <strong>{config.user_name}</strong> → to{' '}
            <strong>{config.manager_name}</strong>
          </p>
        )}
        {config && !configured && (
          <p className="config-warning" role="alert">
            The fixed user and manager are not configured on the backend
            (APPROVAL_USER_NAME and APPROVAL_MANAGER_NAME), so emails cannot be sent.
          </p>
        )}
        {config && !config.buttons_configured && (
          <p className="config-warning" role="note" data-testid="buttons-warning">
            The Approve/Reject buttons are not set up on the backend. Add{' '}
            {buttonsMissing.map((name) => BUTTON_SETTING_WORDS[name]).join(' and ')} to the
            backend .env file and restart it. Sending is disabled until then.
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
            waiting={dashboard.waiting_for_reply}
            nextReminderDueAt={dashboard.next_reminder_due_at}
            config={config}
            onSent={loadDashboard}
            onSendingChange={handleSendingChange}
          />

          <ManagerDecisionsTable decisions={dashboard.recent_decisions} />

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
