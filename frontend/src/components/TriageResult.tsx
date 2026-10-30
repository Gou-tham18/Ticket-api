import React from 'react';
import { TriageResult as TriageResultType, TicketPriority } from '../types/triage';

interface TriageResultProps {
  result: TriageResultType;
}

const PRIORITY_LABELS: Record<TicketPriority, { text: string; badge: string; description: string }> = {
  urgent: {
    text: 'Urgent',
    badge: '🚨 Urgent Priority',
    description: 'Requires immediate triage and response',
  },
  high: {
    text: 'High',
    badge: '▲ High Priority',
    description: 'Needs expedited assistance',
  },
  normal: {
    text: 'Normal',
    badge: '● Normal Priority',
    description: 'Standard support queue',
  },
  low: {
    text: 'Low',
    badge: '▼ Low Priority',
    description: 'Minor priority, non-blocking',
  },
};

export const TriageResult: React.FC<TriageResultProps> = ({ result }) => {
  const priorityInfo = PRIORITY_LABELS[result.priority] || {
    text: result.priority,
    badge: result.priority,
    description: 'Priority level',
  };

  return (
    <section
      className="triage-result"
      aria-labelledby="triage-results-heading"
    >
      <div className="results-header">
        <h2 id="triage-results-heading">Triage Assessment</h2>
        <span className="results-badge" aria-label="AI classification completed">
          Assessed
        </span>
      </div>

      <div className="result-grid">
        <div className="result-card">
          <span className="card-label">Category</span>
          <div className="card-value category-value" data-testid="result-category">
            {result.category}
          </div>
        </div>

        <div className="result-card">
          <span className="card-label">Priority Level</span>
          <div
            className={`card-value priority-badge priority-${result.priority.toLowerCase()}`}
            data-testid="result-priority"
            aria-label={`Priority: ${priorityInfo.text}. ${priorityInfo.description}`}
          >
            <span className="priority-text">{priorityInfo.badge}</span>
            <span className="priority-desc sr-only">{priorityInfo.description}</span>
          </div>
        </div>
      </div>

      <div className="result-card full-width">
        <span className="card-label">Suggested Reply</span>
        <div
          className="card-value suggested-reply"
          data-testid="result-suggested-reply"
        >
          {result.suggested_reply}
        </div>
      </div>

      <div className="result-card full-width">
        <span className="card-label">Relevant Knowledge-Base Articles</span>
        <div
          className="article-tags"
          data-testid="result-article-ids"
          aria-label="Knowledge-base articles referenced"
        >
          {result.article_ids.length > 0 ? (
            result.article_ids.map((id) => (
              <span key={id} className="article-tag">
                📄 {id}
              </span>
            ))
          ) : (
            <span className="no-articles-text">
              No matching knowledge-base articles found.
            </span>
          )}
        </div>
      </div>
    </section>
  );
};

