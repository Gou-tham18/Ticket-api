import React, { useState } from 'react';
import { Decision, DecisionPayload } from '../types/escalation';

interface DecisionFormProps {
  ticketId: string;
  decision: Decision;
  approver: string | null;
  onSubmit: (payload: DecisionPayload) => Promise<void>;
  onCancel: () => void;
}

const MAX_NAME_LENGTH = 100;

export const DecisionForm: React.FC<DecisionFormProps> = ({
  ticketId,
  decision,
  approver,
  onSubmit,
  onCancel,
}) => {
  const [decidedBy, setDecidedBy] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const idPrefix = `decision-${ticketId}`;

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitError(null);

    const trimmed = decidedBy.trim();
    if (!trimmed) {
      setError('Decision-maker name is required and cannot be blank.');
      return;
    }
    if (trimmed.length > MAX_NAME_LENGTH) {
      setError(`Name cannot exceed ${MAX_NAME_LENGTH} characters.`);
      return;
    }

    setIsSubmitting(true);
    try {
      await onSubmit({ decision, decided_by: trimmed });
    } catch (err: unknown) {
      setSubmitError(
        err instanceof Error ? err.message : 'The decision could not be recorded.',
      );
      setIsSubmitting(false);
    }
  };

  return (
    <form
      className={`action-form action-form-${decision.toLowerCase()}`}
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby={`${idPrefix}-heading`}
    >
      <h3 id={`${idPrefix}-heading`} className="action-form-title">
        Record {decision} decision for {ticketId}
      </h3>
      {approver && (
        <p className="action-form-hint">Approval was requested from {approver}.</p>
      )}

      {submitError && (
        <div className="error-message form-submit-error" role="alert">
          {submitError}
        </div>
      )}

      <div className="action-form-fields">
        <div className="form-group">
          <label htmlFor={`${idPrefix}-decided-by`} className="form-label">
            Decision made by <span className="required-indicator" aria-hidden="true">*</span>
          </label>
          <input
            id={`${idPrefix}-decided-by`}
            type="text"
            className={`form-input ${error ? 'input-error' : ''}`}
            value={decidedBy}
            onChange={(e) => {
              setDecidedBy(e.target.value);
              if (error) {
                setError(null);
              }
            }}
            maxLength={MAX_NAME_LENGTH}
            disabled={isSubmitting}
            autoFocus
            aria-required="true"
            aria-invalid={!!error}
            aria-describedby={error ? `${idPrefix}-decided-by-error` : undefined}
          />
          {error && (
            <div id={`${idPrefix}-decided-by-error`} className="error-message" role="alert">
              {error}
            </div>
          )}
        </div>
      </div>

      <div className="form-actions">
        <button
          type="submit"
          className={`btn ${decision === 'Accept' ? 'btn-accept' : 'btn-reject'}`}
          disabled={isSubmitting}
        >
          {isSubmitting ? 'Submitting...' : `Confirm ${decision}`}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          Cancel
        </button>
      </div>
    </form>
  );
};
