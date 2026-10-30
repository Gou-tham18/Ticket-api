import React, { useState } from 'react';
import { DashboardTicket, Indicator } from '../types/dashboard';

export const INDICATOR_LABELS: Record<Indicator, string> = {
  urgent_open: 'Urgent & open',
  escalated_label: 'Escalated label',
  refund_over_200: 'Refund over 200',
};

// Each indicator has its own symbol so it is not told apart by colour alone.
export const INDICATOR_ICONS: Record<Indicator, string> = {
  urgent_open: '!',
  escalated_label: '↑',
  refund_over_200: '$',
};

/** "2026-10-05 13:05" -> "05/10/2026 13:05". Other values are shown as-is. */
export function formatCreated(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(value);
  if (!match) {
    return value;
  }
  const [, year, month, day, hour, minute] = match;
  return `${day}/${month}/${year} ${hour}:${minute}`;
}

export const IndicatorBadge: React.FC<{ indicator: Indicator }> = ({ indicator }) => (
  <span className={`indicator-badge indicator-${indicator}`}>
    <span className="indicator-icon" aria-hidden="true">
      {INDICATOR_ICONS[indicator]}
    </span>
    {INDICATOR_LABELS[indicator]}
  </span>
);

interface DashboardTicketTableProps {
  tickets: DashboardTicket[];
  totalCount: number;
  openCount: number;
}

export const DashboardTicketTable: React.FC<DashboardTicketTableProps> = ({
  tickets,
  totalCount,
  openCount,
}) => {
  const [attentionOnly, setAttentionOnly] = useState(false);
  const shown = attentionOnly ? tickets.filter((t) => t.indicators.length > 0) : tickets;

  return (
    <section className="tickets-section" aria-labelledby="all-tickets-heading">
      <div className="section-header">
        <h2 id="all-tickets-heading" className="section-title">
          All tickets ({totalCount} total, {openCount} open)
        </h2>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={attentionOnly}
            onChange={(e) => setAttentionOnly(e.target.checked)}
          />
          Show only tickets needing attention
        </label>
      </div>

      {shown.length === 0 ? (
        <div className="empty-state">
          <p>No tickets need attention.</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="ticket-table">
            <caption className="sr-only">
              {attentionOnly
                ? `${shown.length} tickets needing attention`
                : `All ${totalCount} tickets from the Help Desk export`}
            </caption>
            <thead>
              <tr>
                <th scope="col">Ticket ID</th>
                <th scope="col">Category</th>
                <th scope="col">Priority</th>
                <th scope="col">Created</th>
                <th scope="col">Status</th>
                <th scope="col">Assigned to</th>
                <th scope="col">Labels</th>
                <th scope="col">Needs attention</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((ticket) => (
                <tr key={ticket.ticket_id} data-testid={`dashboard-row-${ticket.ticket_id}`}>
                  <th scope="row" data-label="Ticket ID" className="ticket-id-cell">
                    {ticket.ticket_id}
                  </th>
                  <td data-label="Category">{ticket.category}</td>
                  <td data-label="Priority">
                    <span
                      className={`priority-badge priority-badge-small priority-${ticket.priority.toLowerCase()}`}
                    >
                      {ticket.priority.charAt(0).toUpperCase() + ticket.priority.slice(1)}
                    </span>
                  </td>
                  <td data-label="Created" className="nowrap">
                    {formatCreated(ticket.created_at)}
                  </td>
                  <td data-label="Status">
                    <span
                      className={`status-badge ${ticket.is_open ? 'status-open' : 'status-resolved'}`}
                    >
                      {ticket.is_open ? 'Open' : 'Resolved'}
                    </span>{' '}
                    <span className="muted-text">{ticket.status}</span>
                  </td>
                  <td data-label="Assigned to">
                    {ticket.assigned_to ?? <span className="muted-text">Unassigned</span>}
                  </td>
                  <td data-label="Labels">
                    {ticket.labels.length > 0 ? ticket.labels.join(', ') : '—'}
                  </td>
                  <td data-label="Needs attention">
                    {ticket.indicators.length > 0 ? (
                      <span className="indicator-list">
                        {ticket.indicators.map((indicator) => (
                          <IndicatorBadge key={indicator} indicator={indicator} />
                        ))}
                      </span>
                    ) : (
                      <span className="muted-text">—</span>
                    )}
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
