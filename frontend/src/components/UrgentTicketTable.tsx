import React from 'react';
import { ApprovalRequestForm } from './ApprovalRequestForm';
import { DecisionForm } from './DecisionForm';
import {
  ApprovalRequestPayload,
  ApprovalStage,
  Decision,
  DecisionPayload,
  UrgentTicket,
} from '../types/escalation';

// Which inline form is open, if any.
export type ActiveAction =
  | { type: 'request'; ticketId: string }
  | { type: 'decision'; ticketId: string; decision: Decision };

interface UrgentTicketTableProps {
  tickets: UrgentTicket[];
  managers: string[];
  activeAction: ActiveAction | null;
  disabled: boolean;
  onOpenAction: (action: ActiveAction) => void;
  onCancelAction: () => void;
  onRequestApproval: (ticketId: string, payload: ApprovalRequestPayload) => Promise<void>;
  onRecordDecision: (ticketId: string, payload: DecisionPayload) => Promise<void>;
}

const STAGE_LABELS: Record<ApprovalStage, string> = {
  not_requested: 'Not requested',
  awaiting_decision: 'Awaiting decision',
  accepted: 'Accepted',
  rejected: 'Rejected',
};

const STATUS_LABELS: Record<string, string> = {
  open: 'Open',
  in_progress: 'In progress',
};

const COLUMN_COUNT = 9;

export function formatHours(hours: number | null): string {
  if (hours === null || Number.isNaN(hours)) {
    return '—';
  }
  const total = Math.round(hours);
  if (total < 1) {
    return '< 1h';
  }
  const days = Math.floor(total / 24);
  const remainder = total % 24;
  return days > 0 ? `${days}d ${remainder}h` : `${remainder}h`;
}

export const UrgentTicketTable: React.FC<UrgentTicketTableProps> = ({
  tickets,
  managers,
  activeAction,
  disabled,
  onOpenAction,
  onCancelAction,
  onRequestApproval,
  onRecordDecision,
}) => {
  const renderActions = (ticket: UrgentTicket) => {
    const isOpen = activeAction?.ticketId === ticket.ticket_id;

    if (ticket.approval_stage === 'not_requested') {
      return (
        <button
          type="button"
          className="btn btn-small btn-primary"
          onClick={() => onOpenAction({ type: 'request', ticketId: ticket.ticket_id })}
          disabled={disabled || isOpen}
          aria-label={`Request approval for ${ticket.ticket_id}`}
        >
          Request Approval
        </button>
      );
    }

    if (ticket.approval_stage === 'awaiting_decision') {
      return (
        <div className="row-actions">
          {(['Accept', 'Reject'] as Decision[]).map((decision) => (
            <button
              key={decision}
              type="button"
              className={`btn btn-small ${decision === 'Accept' ? 'btn-accept' : 'btn-reject'}`}
              onClick={() =>
                onOpenAction({ type: 'decision', ticketId: ticket.ticket_id, decision })
              }
              disabled={disabled || isOpen}
              aria-label={`${decision} ${ticket.ticket_id}`}
            >
              {decision}
            </button>
          ))}
        </div>
      );
    }

    return <span className="muted-text">No action needed</span>;
  };

  const renderForm = (ticket: UrgentTicket) => {
    if (!activeAction || activeAction.ticketId !== ticket.ticket_id) {
      return null;
    }

    const form =
      activeAction.type === 'request' ? (
        <ApprovalRequestForm
          ticketId={ticket.ticket_id}
          managers={managers}
          onSubmit={(payload) => onRequestApproval(ticket.ticket_id, payload)}
          onCancel={onCancelAction}
        />
      ) : (
        <DecisionForm
          ticketId={ticket.ticket_id}
          decision={activeAction.decision}
          approver={ticket.escalation?.approver ?? null}
          onSubmit={(payload) => onRecordDecision(ticket.ticket_id, payload)}
          onCancel={onCancelAction}
        />
      );

    return (
      <tr className="action-row">
        <td colSpan={COLUMN_COUNT}>{form}</td>
      </tr>
    );
  };

  return (
    <div className="table-wrapper">
      <table className="ticket-table">
        <caption className="sr-only">
          Urgent open tickets, ordered so tickets needing action come first
        </caption>
        <thead>
          <tr>
            <th scope="col">Ticket ID</th>
            <th scope="col">Category</th>
            <th scope="col">Priority</th>
            <th scope="col">Status</th>
            <th scope="col">Assigned to</th>
            <th scope="col">Approval stage</th>
            <th scope="col">Ticket age</th>
            <th scope="col">Waiting for decision</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((ticket) => (
            <React.Fragment key={ticket.ticket_id}>
              <tr data-testid={`ticket-row-${ticket.ticket_id}`}>
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
                <td data-label="Status">{STATUS_LABELS[ticket.status] ?? ticket.status}</td>
                <td data-label="Assigned to">
                  {ticket.assigned_to ?? <span className="muted-text">Unassigned</span>}
                </td>
                <td data-label="Approval stage">
                  <span className={`stage-badge stage-${ticket.approval_stage}`}>
                    {STAGE_LABELS[ticket.approval_stage]}
                  </span>
                  {ticket.approval_stage === 'awaiting_decision' &&
                    ticket.escalation?.approver && (
                      <span className="stage-detail">
                        Approver: {ticket.escalation.approver}
                      </span>
                    )}
                </td>
                <td data-label="Ticket age">{formatHours(ticket.age_hours)}</td>
                <td data-label="Waiting for decision">
                  {formatHours(ticket.waiting_for_decision_hours)}
                </td>
                <td data-label="Actions">{renderActions(ticket)}</td>
              </tr>
              {renderForm(ticket)}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
};
