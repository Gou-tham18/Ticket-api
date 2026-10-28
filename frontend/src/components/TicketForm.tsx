import React, { useState } from 'react';
import { TriageRequest, ValidationErrors } from '../types/triage';

interface TicketFormProps {
  isLoading: boolean;
  onSubmit: (data: TriageRequest) => void;
  onReset: () => void;
}

export const TicketForm: React.FC<TicketFormProps> = ({
  isLoading,
  onSubmit,
  onReset,
}) => {
  const [subject, setSubject] = useState('');
  const [text, setText] = useState('');
  const [errors, setErrors] = useState<ValidationErrors>({});

  const validate = (): boolean => {
    const nextErrors: ValidationErrors = {};
    const trimmedSubject = subject.trim();
    const trimmedText = text.trim();

    if (!trimmedSubject) {
      nextErrors.subject = 'Subject is required and cannot be blank.';
    } else if (trimmedSubject.length > 500) {
      nextErrors.subject = 'Subject cannot exceed 500 characters.';
    }

    if (!trimmedText) {
      nextErrors.text = 'Ticket description is required and cannot be blank.';
    } else if (trimmedText.length > 10000) {
      nextErrors.text = 'Ticket description cannot exceed 10,000 characters.';
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!validate()) {
      return;
    }

    onSubmit({
      subject: subject.trim(),
      text: text.trim(),
    });
  };

  const handleClear = () => {
    setSubject('');
    setText('');
    setErrors({});
    onReset();
  };

  const handleSubjectChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSubject(e.target.value);
    if (errors.subject) {
      setErrors((prev) => ({ ...prev, subject: undefined }));
    }
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    if (errors.text) {
      setErrors((prev) => ({ ...prev, text: undefined }));
    }
  };

  return (
    <form className="ticket-form" onSubmit={handleSubmit} noValidate>
      <div className="form-group">
        <div className="label-row">
          <label htmlFor="ticket-subject" className="form-label">
            Subject <span className="required-indicator" aria-hidden="true">*</span>
          </label>
          <span className="char-count" aria-live="off">
            {subject.length} / 500
          </span>
        </div>
        <input
          id="ticket-subject"
          name="subject"
          type="text"
          className={`form-input ${errors.subject ? 'input-error' : ''}`}
          placeholder="e.g. Cannot reset my password"
          value={subject}
          onChange={handleSubjectChange}
          maxLength={500}
          disabled={isLoading}
          aria-required="true"
          aria-invalid={!!errors.subject}
          aria-describedby={errors.subject ? 'subject-error' : undefined}
        />
        {errors.subject && (
          <div id="subject-error" className="error-message" role="alert">
            {errors.subject}
          </div>
        )}
      </div>

      <div className="form-group">
        <div className="label-row">
          <label htmlFor="ticket-description" className="form-label">
            Ticket Description <span className="required-indicator" aria-hidden="true">*</span>
          </label>
          <span className="char-count" aria-live="off">
            {text.length} / 10,000
          </span>
        </div>
        <textarea
          id="ticket-description"
          name="text"
          rows={6}
          className={`form-textarea ${errors.text ? 'input-error' : ''}`}
          placeholder="Describe the issue in detail..."
          value={text}
          onChange={handleTextChange}
          maxLength={10000}
          disabled={isLoading}
          aria-required="true"
          aria-invalid={!!errors.text}
          aria-describedby={errors.text ? 'description-error' : undefined}
        />
        {errors.text && (
          <div id="description-error" className="error-message" role="alert">
            {errors.text}
          </div>
        )}
      </div>

      <div className="form-actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={isLoading}
        >
          {isLoading ? 'Submitting...' : 'Submit for Triage'}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleClear}
          disabled={isLoading}
        >
          Clear
        </button>
      </div>
    </form>
  );
};

