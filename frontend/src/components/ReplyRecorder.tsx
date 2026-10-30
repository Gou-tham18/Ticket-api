import React, { useState } from 'react';
import { ErrorBanner, SuccessBanner, errorText } from './Banners';
import { previewReply, recordReply } from '../services/dashboardApi';
import { ReplyDecision, ReplyResult, ReplyStatus } from '../types/dashboard';

interface ReplyRecorderProps {
  configured: boolean;
  managerName: string | null;
  onRecorded: () => Promise<void>;
}

const MAX_REPLY_LENGTH = 50000;

const DECISION_LABELS: Record<ReplyDecision, string> = {
  accept: 'Approve',
  reject: 'Reject',
  blank: '—',
  unclear: 'Unclear',
};

export const STATUS_LABELS: Record<ReplyStatus, string> = {
  accept: 'Will accept',
  reject: 'Will reject',
  blank: 'Blank',
  unclear: 'Unclear',
  not_found: 'Not found',
  not_awaiting: 'Not awaiting',
};

export const ReplyRecorder: React.FC<ReplyRecorderProps> = ({
  configured,
  managerName,
  onRecorded,
}) => {
  const [replyText, setReplyText] = useState('');
  const [result, setResult] = useState<ReplyResult | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const decisions = result ? result.counts.accept + result.counts.reject : 0;
  // A preview only counts for the text it was made from.
  const isPreview = result !== null && result.recorded === undefined;
  const canRecord = configured && isPreview && decisions > 0 && !isRecording;

  const handleCheck = async () => {
    setError(null);
    setSuccess(null);
    if (!replyText.trim()) {
      setError("Paste the manager's reply before checking it.");
      return;
    }
    setIsChecking(true);
    try {
      setResult(await previewReply(replyText));
    } catch (err: unknown) {
      setResult(null);
      setError(errorText(err, 'The reply could not be checked.'));
    } finally {
      setIsChecking(false);
    }
  };

  const handleRecord = async () => {
    setError(null);
    setIsRecording(true);
    try {
      const recorded = await recordReply(replyText);
      setResult(recorded);
      const ids = recorded.recorded ?? [];
      setSuccess(
        ids.length > 0
          ? `Recorded ${ids.length} decision${ids.length === 1 ? '' : 's'} by ` +
              `${recorded.manager}: ${ids.join(', ')}.`
          : 'No decisions were recorded; see the table for the reason per ticket.',
      );
      setReplyText('');
      await onRecorded();
    } catch (err: unknown) {
      setError(errorText(err, 'The decisions could not be recorded.'));
    } finally {
      setIsRecording(false);
    }
  };

  return (
    <section className="tickets-section" aria-labelledby="reply-heading">
      <div className="section-header">
        <h2 id="reply-heading" className="section-title">
          Record manager&apos;s reply
        </h2>
      </div>

      {success && (
        <SuccessBanner title="Recorded" message={success} onDismiss={() => setSuccess(null)} />
      )}
      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div className="form-group">
        <label htmlFor="reply-text" className="form-label">
          Paste the manager&apos;s reply here
        </label>
        <textarea
          id="reply-text"
          className="form-textarea reply-textarea"
          rows={8}
          value={replyText}
          maxLength={MAX_REPLY_LENGTH}
          onChange={(e) => {
            setReplyText(e.target.value);
            if (isPreview) {
              setResult(null);
            }
          }}
          disabled={!configured || isRecording}
          aria-describedby="reply-hint"
        />
        <p id="reply-hint" className="action-form-hint">
          Decisions are recorded as made by {managerName ?? 'the manager'}. Tickets with no
          clear APPROVE or REJECT stay awaiting a decision.
        </p>
      </div>

      <div className="form-actions">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleCheck}
          disabled={!configured || isChecking || isRecording}
        >
          {isChecking ? 'Checking...' : 'Check reply'}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleRecord}
          disabled={!canRecord}
        >
          {isRecording ? 'Recording...' : 'Record decisions'}
        </button>
      </div>

      {result && (
        <div className="table-wrapper reply-results">
          <table className="ticket-table">
            <caption className="sr-only">
              {isPreview ? 'Decisions understood from the reply' : 'Decisions recorded'}
            </caption>
            <thead>
              <tr>
                <th scope="col">Ticket ID</th>
                <th scope="col">Understood decision</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {result.tickets.map((ticket) => (
                <tr key={ticket.ticket_id} data-testid={`reply-row-${ticket.ticket_id}`}>
                  <th scope="row" data-label="Ticket ID" className="ticket-id-cell">
                    {ticket.ticket_id}
                  </th>
                  <td data-label="Understood decision">
                    {DECISION_LABELS[ticket.decision] ?? ticket.decision}
                  </td>
                  <td data-label="Status">
                    <span className={`reply-status reply-status-${ticket.status}`}>
                      {STATUS_LABELS[ticket.status]}
                    </span>
                    <span className="stage-detail">{ticket.reason}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
