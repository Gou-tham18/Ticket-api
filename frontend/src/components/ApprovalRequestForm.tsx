import React, { useState } from 'react';
import { ApprovalRequestPayload } from '../types/escalation';

interface ApprovalRequestFormProps {
  ticketId: string;
  managers: string[];
  onSubmit: (payload: ApprovalRequestPayload) => Promise<void>;
  onCancel: () => void;
}

interface FieldErrors {
  requestedBy?: string;
  approver?: string;
}

const MAX_NAME_LENGTH = 100;

export const ApprovalRequestForm: React.FC<ApprovalRequestFormProps> = ({
  ticketId,
  managers,
  onSubmit,
  onCancel,
}) => {
  const [requestedBy, setRequestedBy] = useState('');
  const [approver, setApprover] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const idPrefix = `request-${ticketId}`;

  const validate = (): boolean => {
    const nextErrors: FieldErrors = {};
    const trimmed = requestedBy.trim();

    if (!trimmed) {
      nextErrors.requestedBy = 'Your name is required and cannot be blank.';
    } else if (trimmed.length > MAX_NAME_LENGTH) {
      nextErrors.requestedBy = `Name cannot exceed ${MAX_NAME_LENGTH} characters.`;
    }

    if (!approver) {
      nextErrors.approver = 'Select the manager who should approve.';
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitError(null);
    if (!validate()) {
      return;
    }

    setIsSubmitting(true);
    try {
      await onSubmit({ requested_by: requestedBy.trim(), approver });
    } catch (err: unknown) {
      setSubmitError(
        err instanceof Error ? err.message : 'The approval request could not be recorded.',
      );
      setIsSubmitting(false);
    }
  };

  const noManagers = managers.length === 0;

  return (
    <form
      className="action-form"
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby={`${idPrefix}-heading`}
    >
      <h3 id={`${idPrefix}-heading`} className="action-form-title">
        Request approval for {ticketId}
      </h3>
      <p className="action-form-hint">
        This records the request in the tracker log. It does not send an email, so
        let the manager know separately.
      </p>

      {submitError && (
        <div className="error-message form-submit-error" role="alert">
          {submitError}
        </div>
      )}

      <div className="action-form-fields">
        <div className="form-group">
          <label htmlFor={`${idPrefix}-requested-by`} className="form-label">
            Your name <span className="required-indicator" aria-hidden="true">*</span>
          </label>
          <input
            id={`${idPrefix}-requested-by`}
            type="text"
            className={`form-input ${errors.requestedBy ? 'input-error' : ''}`}
            value={requestedBy}
            onChange={(e) => {
              setRequestedBy(e.target.value);
              if (errors.requestedBy) {
                setErrors((prev) => ({ ...prev, requestedBy: undefined }));
              }
            }}
            maxLength={MAX_NAME_LENGTH}
            disabled={isSubmitting}
            autoFocus
            aria-required="true"
            aria-invalid={!!errors.requestedBy}
            aria-describedby={errors.requestedBy ? `${idPrefix}-requested-by-error` : undefined}
          />
          {errors.requestedBy && (
            <div id={`${idPrefix}-requested-by-error`} className="error-message" role="alert">
              {errors.requestedBy}
            </div>
          )}
        </div>

        <div className="form-group">
          <label htmlFor={`${idPrefix}-approver`} className="form-label">
            Manager <span className="required-indicator" aria-hidden="true">*</span>
          </label>
          <select
            id={`${idPrefix}-approver`}
            className={`form-input ${errors.approver ? 'input-error' : ''}`}
            value={approver}
            onChange={(e) => {
              setApprover(e.target.value);
              if (errors.approver) {
                setErrors((prev) => ({ ...prev, approver: undefined }));
              }
            }}
            disabled={isSubmitting || noManagers}
            aria-required="true"
            aria-invalid={!!errors.approver}
            aria-describedby={errors.approver ? `${idPrefix}-approver-error` : undefined}
          >
            <option value="">Select a manager</option>
            {managers.map((manager) => (
              <option key={manager} value={manager}>
                {manager}
              </option>
            ))}
          </select>
          {errors.approver && (
            <div id={`${idPrefix}-approver-error`} className="error-message" role="alert">
              {errors.approver}
            </div>
          )}
          {noManagers && (
            <div className="error-message">
              The backend returned no managers, so approval cannot be requested.
            </div>
          )}
        </div>
      </div>

      <div className="form-actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={isSubmitting || noManagers}
        >
          {isSubmitting ? 'Submitting...' : 'Submit request'}
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
