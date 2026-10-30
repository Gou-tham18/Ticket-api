export type TicketCategory =
  | 'Billing'
  | 'Login'
  | 'Shipping'
  | 'Refunds'
  | 'Technical'
  | 'Account';

export type TicketPriority = 'urgent' | 'high' | 'normal' | 'low';

export interface TriageRequest {
  subject: string;
  text: string;
}

export interface TriageResult {
  category: TicketCategory;
  priority: TicketPriority;
  suggested_reply: string;
  article_ids: string[];
}

export interface ValidationErrors {
  subject?: string;
  text?: string;
}

