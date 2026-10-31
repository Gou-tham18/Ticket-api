import React from 'react';
import { DecisionBadge, formatCreated } from './DashboardTicketTable';
import { RecentDecision } from '../types/dashboard';

interface ManagerDecisionsTableProps {
  // Newest first, as returned by the API.
  decisions: RecentDecision[];
}

export const ManagerDecisionsTable: React.FC<ManagerDecisionsTableProps> = ({ decisions }) => (
  <section className="tickets-section" aria-labelledby="decisions-heading">
    <div className="section-header">
      <h2 id="decisions-heading" className="section-title">
        Manager decisions
      </h2>
    </div>

    {decisions.length === 0 ? (
      <div className="empty-state">
        <p>No decisions recorded yet.</p>
      </div>
    ) : (
      <div className="table-wrapper">
        <table className="ticket-table">
          <caption className="sr-only">
            Decisions recorded through the dashboard, newest first
          </caption>
          <thead>
            <tr>
              <th scope="col">Ticket ID</th>
              <th scope="col">Category</th>
              <th scope="col">Decision</th>
              <th scope="col">Decided by</th>
              <th scope="col">Decided at</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((decision) => (
              <tr key={decision.ticket_id} data-testid={`decision-row-${decision.ticket_id}`}>
                <th scope="row" data-label="Ticket ID" className="ticket-id-cell">
                  {decision.ticket_id}
                </th>
                <td data-label="Category">{decision.category}</td>
                <td data-label="Decision">
                  <DecisionBadge decision={decision.decision} />
                </td>
                <td data-label="Decided by">{decision.decided_by ?? '—'}</td>
                <td data-label="Decided at" className="nowrap">
                  {decision.decided_at ? formatCreated(decision.decided_at) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </section>
);
