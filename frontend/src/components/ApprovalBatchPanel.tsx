import React, { useState } from 'react';
import { ErrorBanner, SuccessBanner, errorText } from './Banners';
import { fetchBatchPreview, sendApprovalBatch } from '../services/dashboardApi';
import { ApprovalConfig, BatchPreview, Dashboard } from '../types/dashboard';

interface ApprovalBatchPanelProps {
  batch: Dashboard['approval_batch'];
  config: ApprovalConfig | null;
  onSent: () => Promise<void>;
}

function listOrNone(ids: string[]): string {
  return ids.length > 0 ? ids.join(', ') : 'none';
}

export const ApprovalBatchPanel: React.FC<ApprovalBatchPanelProps> = ({
  batch,
  config,
  onSent,
}) => {
  const [preview, setPreview] = useState<BatchPreview | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const configured = Boolean(config?.configured);
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

      {isEmpty ? (
        <div className="empty-state">
          <p>No urgent open tickets need a decision.</p>
        </div>
      ) : (
        <>
          <ul className="batch-list" aria-label="Tickets in the next approval email">
            {batch.tickets.map((ticket) => (
              <li key={ticket.ticket_id} className="batch-line">
                <code>{ticket.summary_line}</code>
                <span className={`stage-badge stage-${ticket.approval_stage}`}>
                  {ticket.approval_stage === 'not_requested' ? 'New request' : 'Reminder'}
                </span>
              </li>
            ))}
          </ul>
          <p className="fields-saved" data-testid="fields-saved">
            {batch.count} escalations prepared automatically: {batch.fields_saved} ticket
            fields that didn't need to be copied by hand ({batch.count} tickets × 8 fields)
          </p>
        </>
      )}

      {!emailConfigured && configured && (
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
          disabled={!configured || isEmpty || isLoadingPreview}
          aria-expanded={showPreview}
          aria-controls="email-preview"
        >
          {showPreview ? 'Hide email preview' : 'Preview email'}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSend}
          disabled={!configured || !emailConfigured || isEmpty || isSending}
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
              <pre className="email-body">{preview.body}</pre>
            </>
          )}
        </div>
      )}
    </section>
  );
};
