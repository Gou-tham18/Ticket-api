import React, { useEffect, useRef } from 'react';

interface ErrorBannerProps {
  message: string;
  onDismiss?: () => void;
  onRetry?: () => void;
  retryDisabled?: boolean;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  message,
  onDismiss,
  onRetry,
  retryDisabled,
}) => (
  <div className="error-banner" role="alert" aria-live="assertive">
    <div className="error-icon" aria-hidden="true">⚠️</div>
    <div className="error-content">
      <strong>Error</strong>
      <p>{message}</p>
    </div>
    {onRetry && (
      <button
        type="button"
        className="btn btn-secondary btn-small"
        onClick={onRetry}
        disabled={retryDisabled}
      >
        Retry
      </button>
    )}
    {onDismiss && (
      <button
        type="button"
        className="error-dismiss-btn"
        onClick={onDismiss}
        aria-label="Dismiss error message"
      >
        ×
      </button>
    )}
  </div>
);

interface SuccessBannerProps {
  title: string;
  message: string;
  onDismiss: () => void;
}

export const SuccessBanner: React.FC<SuccessBannerProps> = ({ title, message, onDismiss }) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, [message]);

  return (
    <div ref={ref} className="success-banner" role="status" aria-live="polite" tabIndex={-1}>
      <div className="success-icon" aria-hidden="true">✓</div>
      <div className="error-content">
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
      <button
        type="button"
        className="error-dismiss-btn success-dismiss-btn"
        onClick={onDismiss}
        aria-label="Dismiss success message"
      >
        ×
      </button>
    </div>
  );
};

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}
