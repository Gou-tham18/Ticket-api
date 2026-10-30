import React from 'react';
import { UrgentOpenAnalysis } from '../types/escalation';

interface EscalationSummaryProps {
  analysis: UrgentOpenAnalysis;
  isFiltered: boolean;
}

export const EscalationSummary: React.FC<EscalationSummaryProps> = ({
  analysis,
  isFiltered,
}) => {
  const stats = [
    {
      key: 'total',
      label: 'Urgent open tickets',
      value: analysis.total,
      tone: 'neutral',
    },
    {
      key: 'not-requested',
      label: 'Not yet sent for approval',
      value: analysis.by_stage.not_requested,
      tone: 'warning',
    },
    {
      key: 'awaiting',
      label: 'Awaiting decision',
      value: analysis.by_stage.awaiting_decision,
      tone: 'info',
    },
    {
      key: 'accepted',
      label: 'Accepted',
      value: analysis.by_stage.accepted,
      tone: 'success',
    },
    {
      key: 'rejected',
      label: 'Rejected',
      value: analysis.by_stage.rejected,
      tone: 'danger',
    },
  ];

  return (
    <section className="summary-section" aria-labelledby="escalation-summary-heading">
      <h2 id="escalation-summary-heading" className="section-title">
        Summary
        {isFiltered && <span className="section-note"> (matching current filters)</span>}
      </h2>
      <dl className="stat-grid">
        {stats.map((stat) => (
          <div
            key={stat.key}
            className={`stat-tile stat-${stat.tone}`}
            data-testid={`stat-${stat.key}`}
          >
            <dt className="stat-label">{stat.label}</dt>
            <dd className="stat-value">{stat.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
};
