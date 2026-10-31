import React, { useState } from 'react';
import { ErrorBanner, SuccessBanner, errorText } from './Banners';
import { formatCreated } from './DashboardTicketTable';
import { fetchBatchPreview, sendApprovalBatch } from '../services/dashboardApi';
import {
  ApprovalConfig,
  BatchPreview,
  BatchTicket,
  Dashboard,
  WaitingTicket,
} from '../types/dashboard';

interface ApprovalBatchPanelProps {
  batch: Dashboard['approval_batch'];
  waiting: WaitingTicket[];
  nextReminderDueAt: string | null;
  config: ApprovalConfig | null;
  onSent: () => Promise<void>;
  // Lets the dashboard pause auto-refresh while an email is being sent.
  onSendingChange?: (isSending: boolean) => void;
}

// The preview shows the real links; make them inert inside the iframe.
const PREVIEW_NO_CLICK_STYLE = '<style>a{pointer-events:none;cursor:default}</style>';

function listOrNone(ids: string[]): string {
  return ids.length > 0 ? ids.join(', ') : 'none';
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

const SendReasonBadge: React.FC<{ ticket: BatchTicket }> = ({ ticket }) =>
  ticket.send_reason === 'new' ? (
    <span className="stage-badge stage-not_requested">New</span>
  ) : (
    <span className="stage-badge stage-awaiting_decision">
      Reminder
      {ticket.days_waiting !== null && ` · waiting ${plural(ticket.days_waiting, 'day')}`}
    </span>
  );

export const ApprovalBatchPanel: React.FC<ApprovalBatchPanelProps> = ({
  batch,
  waiting,
  nextReminderDueAt,
  config,
  onSent,
  onSendingChange,
}) => {
  const [preview, setPreview] = useState<BatchPreview | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const configured = Boolean(config?.configured);
  const buttonsConfigured = Boolean(config?.buttons_configured);
  const emailConfigured = Boolean(config?.email_configured);
  const isEmpty = batch.count === 0;

  const togglePreview = async () => {
    if (showPreview) {
      setShowPreview(false);
      return;
    }
    setShowPreview(true);
    setIsLoadingPreview(true);
    setError(null);
    try {
      setPreview(await fetchBatchPreview());
    } catch (err: unknown) {
      setShowPreview(false);
      setError(errorText(err, 'The email preview could not be loaded.'));
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const handleSend = async () => {
    setIsSending(true);
    onSendingChange?.(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await sendApprovalBatch();
      setSuccess(
        `Email sent to ${config?.manager_name ?? 'the manager'} with ` +
          `${result.ticket_ids.length} tickets. ` +
          `Newly requested: ${listOrNone(result.newly_requested)}. ` +
          `Reminders: ${listOrNone(result.reminders)}.`,
      );
      setPreview(null);
      setShowPreview(false);
      await onSent();
    } catch (err: unknown) {
      setError(errorText(err, 'Approval email could not be sent.'));
    } finally {
      setIsSending(false);
      onSendingChange?.(false);
    }
  };

  return (
    <section className="tickets-section" aria-labelledby="batch-heading">
      <div className="section-header">
        <h2 id="batch-heading" className="section-title">
          Escalations awaiting manager approval
        </h2>
      </div>

      {success && (
        <SuccessBanner title="Sent" message={success} onDismiss={() => setSuccess(null)} />
      )}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <h3 className="subsection-title">Ready to send</h3>
      {isEmpty ? (
        <div className="empty-state" data-testid="batch-empty">
          {waiting.length > 0 ? (
            <p>
              Nothing to send right now. {plural(waiting.length, 'ticket')}{' '}
              {waiting.length === 1 ? 'is' : 'are'} waiting for the manager&apos;s decision.
              {nextReminderDueAt &&
                ` The next reminder is due ${formatCreated(nextReminderDueAt)}.`}
            </p>
          ) : (
            <p>No urgent open tickets need a decision.</p>
          )}
        </div>
      ) : (
        <>
          <ul className="batch-list" aria-label="Tickets in the next approval email">
            {batch.tickets.map((ticket) => (
              <li
                key={ticket.ticket_id}
                className="batch-line"
                data-testid={`batch-line-${ticket.ticket_id}`}
              >
                <code>{ticket.summary_line}</code>
                <SendReasonBadge ticket={ticket} />
              </li>
            ))}
          </ul>
          <p className="fields-saved" data-testid="fields-saved">
            {batch.count} escalations prepared automatically: {batch.fields_saved} ticket
            fields that didn't need to be copied by hand ({batch.count} tickets × 8 fields)
          </p>
        </>
      )}

      {!emailConfigured && configured && buttonsConfigured && (
        <p className="config-warning" role="note">
          Email sending is not configured on the backend (SMTP or email addresses), so
          the email cannot be sent yet.
        </p>
      )}

      <div className="form-actions">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={togglePreview}
          disabled={!configured || !buttonsConfigured || isEmpty || isLoadingPreview}
          aria-expanded={showPreview}
          aria-controls="email-preview"
        >
          {showPreview ? 'Hide email preview' : 'Preview email'}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSend}
          disabled={!configured || !emailConfigured || !buttonsConfigured || isEmpty || isSending}
        >
          {isSending ? 'Sending...' : 'Send to manager for approval'}
        </button>
      </div>

      {showPreview && (
        <div id="email-preview" className="email-preview" aria-busy={isLoadingPreview}>
          {isLoadingPreview || !preview ? (
            <p className="muted-text">Loading preview...</p>
          ) : (
            <>
              <p>
                <strong>To:</strong> {preview.to} &nbsp; <strong>From:</strong> {preview.from}
              </p>
              <p>
                <strong>Subject:</strong> {preview.subject}
              </p>
              <p className="muted-text">Links in the preview are not clickable.</p>
              {/* No sandbox permissions: no scripts, forms or navigation. */}
              <iframe
                className="email-preview-frame"
                title="Approval email preview"
                sandbox=""
                srcDoc={PREVIEW_NO_CLICK_STYLE + preview.html_body}
              />
            </>
          )}
        </div>
      )}

      {waiting.length > 0 && (
        <>
          <h3 className="subsection-title">Waiting for the manager&apos;s reply</h3>
          <ul className="batch-list" aria-label="Tickets waiting for the manager's reply">
            {waiting.map((ticket) => (
              <li
                key={ticket.ticket_id}
                className="batch-line"
                data-testid={`waiting-line-${ticket.ticket_id}`}
              >
                <code>{ticket.summary_line}</code>
                <span className="stage-detail">
                  Emailed {formatCreated(ticket.last_emailed_at)} · comes back{' '}
                  {formatCreated(ticket.reminder_due_at)} if no decision
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
};
