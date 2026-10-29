# Task 5: Escalation tracking prototype

## Summary

The support team copies ticket details from the Help Desk into a spreadsheet and chases managers for approval by email. This prototype reads the files they already have, the Help Desk export and the escalation tracker, joins them by ticket ID, and lets someone record an Accept or Reject decision against the right ticket, with who decided and when. It does not replace either tool, send email, or add a dashboard.

## Requirements checked against the sources

Before building, the Task 5 requirements were compared with Mara's original email (`client_request.md`), the scoping note, and the two sample files. Most requirements matched. The differences below shaped the design.

| Requirement or claim | What the sources show | How the prototype handles it |
|---|---|---|
| Outcomes are Accept or Reject | The tracker uses `approved`, `Approved`, `OK`, `rejected`, `Rejected`, `Need more info`, and blank | `approved`/`OK` map to Accept and `rejected` maps to Reject. `Need more info` and blank mean no final decision yet (state `pending`). The raw value is kept in `tracker_decision_raw`. Unknown values are treated as pending and listed in data issues. |
| Two managers approve | The tracker's `approver` column only contains Anil and Joyce | Consistent. |
| Who may decide | Task 5 says two managers are responsible. The scoping note says a manager or one of the six team members can decide. | Conflicting, so the prototype does not enforce a list of allowed deciders. `decided_by` is free text. See open questions. |
| Six-member technical team | The export's `assigned_to` has six people: ken, lia, riya, sam, tom, zoe | Consistent. |
| Record decision-maker and timestamp "where supported by the data" | The tracker has `approver` and `decided_at`, but not who actually made the decision | For tracker decisions, `decided_by` shows the tracker's approver and `decision_source` is `tracker`. For decisions recorded in the prototype, `decided_by` is what the user entered and `decided_at` is the server time. |
| Dates | `decided_at` mixes `2026-10-08 02:26` with `08/10/2026 02:26` | Read with the existing `parse_timestamp()` from Day 1. The day-first reading is confirmed by the data: decisions land hours after the request, not months. |
| Escalated tickets | The `labels` column (called `tags` in older exports) uses `escalated`, `Escalated`, `ESCALATED`, `esc`, sometimes combined with `;vip` | All spellings are recognised. A ticket counts as escalated if it has an escalation tag or a tracker row. |
| Reuse supplied data | Tracker has one exact duplicate row (TCK-5111) and one row for a ticket not in the export (TCK-4999) | The duplicate is ignored, the orphan is not linked to anything, and both are listed at `/escalations/data-issues`. |
| "Know the moment something is escalated" (Mara's email) | Not in the Task 5 requirements; the scope excludes notifications unless confirmed | Not built. See open questions. |
| Managers "live in their email and will not learn a new tool" (Mara's email) | The Task 5 scope excludes email integration | Built later as the email approval round trip (below). The manager answers in an email and never opens the app. |
| Billing hurts most, but must work for every team | Export has six categories | No category is hardcoded. Every list endpoint takes a `category` filter. |

Two observations from the sample data were not requirements but are relevant to the problem:

- Six tickets are tagged as escalated but have no tracker row: TCK-5017, TCK-5034, TCK-5042, TCK-5070, TCK-5092, TCK-5110. That is the manual copy step being missed. They appear as `pending` with `in_tracker: false`.
- Three tracker rows are still undecided although the ticket is already resolved or closed: TCK-5063, TCK-5102, TCK-5109.

## What was built

New module `app/escalations.py` and new endpoints in `app/main.py`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/helpdesk/tickets` | Tickets from the Help Desk export with ID, category, priority, created date, status, `is_open`, and escalation details. Filters: `status`, `category`, `priority`, `open_only`, `escalated`. |
| GET | `/helpdesk/tickets/{ticket_id}` | One ticket with its escalation details. |
| GET | `/escalations` | Escalated tickets only. Filters: `state` (`pending`, `accepted`, `rejected`), `category`, `open_only`. |
| GET | `/escalations/data-issues` | Problems found while reading the files (duplicates, orphans, unreadable values). |
| POST | `/escalations/{ticket_id}/decision` | Record `{"decision": "Accept" or "Reject", "decided_by": "Joyce"}`. |

`open` and `in_progress` count as open; `resolved` and `closed` do not.

The view most directly tied to the approval-chasing problem is open escalations still waiting for a decision:

```
GET /escalations?state=pending&open_only=true
```

On the sample data this returns nine tickets.

Decision rules:

- The ticket must exist in the export (`404` otherwise) and be escalated (`409` otherwise).
- A ticket that already has a final decision cannot be decided again (`409`). This avoids silently overwriting a manager's decision.
- `decision` must be exactly `Accept` or `Reject`, and `decided_by` must not be blank (`422` otherwise).

Recorded decisions are appended to `data/decision_log.csv` (configurable with `DECISION_LOG_PATH`). The export and tracker files are never modified. The log is a plain CSV so it can be opened next to the existing spreadsheet, and it is reloaded on restart or when the file changes. A row with an unreadable date is still loaded, with the date left blank, and is listed in data issues.

Configuration, with defaults pointing to the supplied samples:

| Variable | Default |
|---|---|
| `HELPDESK_EXPORT_PATH` | `data/helpdesk_export_sample.csv` |
| `ESCALATION_TRACKER_PATH` | `data/escalation_tracker_sample.csv` |
| `DECISION_LOG_PATH` | `data/decision_log.csv` |

## Urgent open tickets and manager approval

Added after the first version, to analyse urgent tickets that are still open and get them approved by a manager.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/approvals/urgent-open` | Urgent tickets with status `open` or `in_progress`, each with an `approval_stage`, `age_hours`, and `waiting_for_decision_hours`. Returns counts by stage and category, and the list of managers. Filters: `category`, `status` (`open` or `in_progress`). |
| POST | `/approvals/{ticket_id}/request` | Request approval: `{"requested_by": "Lia", "approver": "Joyce"}`. |

Approval stages:

| Stage | Meaning |
|---|---|
| `not_requested` | Urgent and open, but nobody has asked a manager yet (no tracker row or prototype request). |
| `awaiting_decision` | Requested, but no Accept or Reject yet. `Need more info` counts here. |
| `accepted` / `rejected` | A final decision exists. |

Tickets are sorted so the ones needing action come first: `not_requested`, then `awaiting_decision`, oldest first within each. `needs_action` is the count of those two stages.

Rules for requesting approval:

- The approver must be a manager. By default the managers are the approvers already named in the tracker (Anil and Joyce in the sample). Set `MANAGERS=Anil,Joyce` to fix the list explicitly. Names match case-insensitively.
- A ticket can only be requested once (`409` if it already has a tracker row or prototype request).
- Requests are appended to `data/approval_requests.csv` (`APPROVAL_REQUEST_LOG_PATH`). The tracker spreadsheet is not modified. After a request, the ticket can be decided with `POST /escalations/{ticket_id}/decision`.
- Any ticket in the export can be requested, not only urgent ones.

On the sample data, 10 urgent tickets are open. 6 are accepted, 2 are awaiting a manager (TCK-5007 and TCK-5050, both waiting more than two weeks), and 2 were escalated but never sent for approval (TCK-5070 and TCK-5110).

Assumptions:

- "Open" means status `open` or `in_progress`, as elsewhere in this prototype. Use `status=open` for the narrower meaning.
- "Urgent" means priority `urgent` exactly. `high` is not included.
- Ages are measured from the server clock, so on old sample data they are large.

## Email approval round trip

Added to remove the manual copying and the email chasing. One fixed team member (the user) sends one email to one fixed manager. The manager answers in the email and never opens the app.

1. The **Escalation Dashboard** (`/#/dashboard`) collects the urgent open tickets that need a decision and emails them to the manager (`POST /approvals/batch/send`).
2. The manager writes APPROVE or REJECT after `Decision:` under each ticket and replies.
3. The user pastes the reply into the dashboard. `POST /approvals/reply/preview` shows what was understood, and `POST /approvals/reply/record` records it.

### Fixed user and manager

Set in the backend `.env`: `APPROVAL_USER_NAME`, `APPROVAL_USER_EMAIL`, `APPROVAL_MANAGER_NAME`, `APPROVAL_MANAGER_EMAIL`, and `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`.

- Approval requests created by the email use `requested_by` = user and `approver` = manager. Decisions from a reply use `decided_by` = manager.
- The manager is always added to the service's manager list, next to the tracker's approvers or `MANAGERS`, so `request_approval()` accepts them.
- Missing names give `503` on the email endpoints, naming the setting. `/approvals/config` returns only the two names and two booleans: no addresses and no SMTP details.
- The SMTP password is only read by the backend. It is never returned, and it is masked if it appears in a logged error.

### What goes in the email

Urgent open tickets whose approval stage is `not_requested` or `awaiting_decision`, oldest first. Accepted and rejected tickets are never sent. On the current data (with TCK-5070 accepted in `data/decision_log.csv`) that is TCK-5007, TCK-5110, and TCK-5050. Each ticket is one line with the eight export fields other than `customer_email`, then `Decision:`:

```
TCK-5007 | Refunds | urgent | created 05/10/2026 13:05 | in_progress | assigned to riya | labels escalated | refund 480.00
Decision:
```

Dates are `DD/MM/YYYY HH:MM`, labels are lowercased and comma-separated, refunds have two decimals, and empty values are `—`. The subject is `Urgent tickets awaiting your approval (N)`. `Reply-To` is the user's address.

Sending uses `smtplib` from the standard library. Nothing is recorded unless the email is sent. After a successful send, each `not_requested` ticket gets a row in `data/approval_requests.csv` through the existing `request_approval()`. Tickets already awaiting a decision are included as reminders and get no new row. If no tickets need a decision, the response is `409` and nothing is sent. Missing SMTP settings give `503`, and a failed send gives `502` with nothing recorded.

### Reading the reply

Implemented in `app/approval_reply.py`.

- Leading quote markers (`>` and spaces) are removed from each line, and lines containing the "APPROVE or REJECT" instruction are ignored wherever they appear. Otherwise, the quoted instruction under the manager's last answer would make that ticket look conflicting.
- Ticket IDs match `TCK-\d+`. Text before the first ID is ignored. Each occurrence's decision comes from the text between it and the next ID.
- Whole words, case-insensitive. Accept: `approve`, `approved`, `accept`, `accepted`, `ok`, `yes`. Reject: `reject`, `rejected`, `decline`, `declined`, `no`. `no` does not match inside `note`.
- A ticket that appears several times (the answer plus the quoted original) ignores its blank occurrences. Disagreeing answers, or one block with both kinds of word, make it `unclear`.

Each ticket gets one status with a reason:

| Status | Meaning |
|---|---|
| `accept` / `reject` | Will be recorded (preview) or was recorded (record). |
| `blank` | No decision written. Stays awaiting and is included in the next email. |
| `unclear` | Conflicting words. Not recorded. |
| `not_found` | Not in the Help Desk export. |
| `not_awaiting` | Already decided, or approval was never requested. Not recorded; existing decisions are never overwritten. |

The record endpoint parses the text again on the server instead of trusting the preview. Recording the same reply twice adds nothing, because the tickets are no longer awaiting. If no ticket ID is found, the response is `422`.

### Dashboard data

`GET /dashboard` returns every export ticket in export order, without `customer_email`. Each ticket has its labels as a list, the refund as a number, `indicators` and, for urgent open tickets, `approval_stage`. Indicators apply to open tickets only:

- `urgent_open`: priority exactly `urgent`.
- `escalated_label`: any escalation tag spelling, using `is_escalation_tag_set()`.
- `refund_over_200`: refund greater than 200. A blank refund is not over 200. An unreadable non-blank refund is also not over 200, and is listed in data issues.

On the sample data: 120 tickets, 79 open, 10 urgent open, 23 with an escalated label, and 7 with a refund over 200. 23 open tickets match at least one condition. The response also includes `approval_batch`, the next email's tickets, with `fields_saved` = tickets × 8.

### Approval stage fix

`approval_stage()` reported `not_requested` for a ticket that had a final decision but no tracker row, for example a tagged ticket decided with `POST /escalations/{id}/decision`, even though its state was `accepted` or `rejected`. A final decision now wins: `accepted`/`rejected` first, then `not_requested` if the ticket was never requested, then `awaiting_decision`. A regression test covers it.

## Production basics

Added in Task 6. Behaviour of the dashboard, approval email, and reply reading is unchanged.

### Error behaviour

| Case | Result |
|---|---|
| Ticket CSV (`TICKETS_DATA_PATH`) missing or unreadable at startup | Logged, and the server starts anyway. `/tickets`, `/tickets/{id}` and `/summary` return `503` "Ticket data file '<name>' was not found. Check TICKETS_DATA_PATH." (or "could not be read"). The file is retried on the next request |
| Help Desk export missing | `503` on Task 5 endpoints: "Help Desk export '<name>' was not found. Check HELPDESK_EXPORT_PATH." |
| Help Desk export without a `ticket_id` column, or not readable (encoding, permissions) | `503` with a plain message naming the file |
| Escalation tracker missing or unreadable | Treated as empty and listed in `/escalations/data-issues`; the export alone is used |
| Log file missing | Created with a header on the first write |
| Log file not writable (permissions, or open in Excel) | `503` "Could not save to <name>. Close it if it is open in Excel and try again." The row is written in one call, so it is never half-written, and memory changes only after the write succeeds. Sending the approval email and recording a reply check the log first, so no email goes out and no decision is saved if the log is locked |
| Non-numeric `refund_amount`, unreadable date, short or long row | Treated as blank (extra fields dropped) and listed in `/escalations/data-issues` |
| Any other unhandled exception | `500` `{"detail": "Something went wrong on the server. …", "error_id": "<8 hex chars>"}`. The traceback is logged with the same ID. CORS headers are kept, so the browser can show the message |

The existing triage `502`/`503`, email `502`/`503` and `404`/`409`/`422` responses are unchanged. The frontend shows a 503's message (for example, "Ticket triage is not configured…") and a 500's message with "(Error ID: …)".

### Validation

- Validation errors keep FastAPI's shape (`detail` list with `loc` and `msg`). Each `msg` is a plain sentence naming the field, for example "subject is required.", "subject must be 500 characters or fewer.", "decision must be Accept or Reject.", "page must be 1 or more.", or "The request body is not valid JSON.". A top-level `message` repeats the first problem.
- `ticket_id` on `/helpdesk/tickets/{id}`, `/approvals/{id}/request` and `/escalations/{id}/decision` must match `TCK-` followed by 1 to 10 digits, otherwise "Ticket IDs look like TCK-5007." `/tickets/{id}` (Task 3) is unchanged.
- On `/helpdesk/tickets`, `status` must be open, in_progress, resolved, or closed, and `priority` must be urgent, high, normal, or low. Matching is case-insensitive. `category` is free text up to 50 characters on every endpoint that takes it.
- Empty or whitespace-only `requested_by`, `approver`, `decided_by`, `subject` and `text` give "<field> must not be blank." An empty `reply_text` gives "Paste the manager's reply before checking it."

### Health check

`GET /health` always returns `200` while the process runs. It checks `ticket_data`, `helpdesk_export` and `escalation_tracker` (`ok`, `missing`, or `unreadable`), and `logs_writable` (`ok` or `not_writable`, using permission checks only, without creating or changing a log). It also reports `triage_ai` and `approval_email` (`configured` or `not_configured`). `status` is `degraded` if a file or log check fails. It never calls Gemini or the mail server, and it never includes keys, addresses, names, or paths.

## Existing functionality

`/tickets`, `/summary`, `/triage`, and the static page are unchanged by the email round trip. `/tickets` and `/summary` read `TICKETS_DATA_PATH`, which now defaults to the Help Desk export. The Escalation Tracker page (`/#/escalations`) works as before.

## Tests

`tests/test_escalations.py` has 69 tests, `tests/test_email_approval.py` has 61, and `tests/test_production.py` (Task 6: errors, validation, `/health`) has 64, for 222 in total across the backend. The email tests use copies of the sample files in a temporary folder and a fake email sender, so they never open a network connection or write to `data/`. They cover decision and tag normalisation, day-first dates, open versus resolved status, joining the tracker to the export, duplicate and orphan handling, recording decisions, persistence across a restart, the source files staying untouched, every API error path, the urgent-open analysis, and manager approval requests. Four tests run against the supplied sample files and check the exact counts and issues listed above.

```
python -m pytest -q
```

## Limitations

- Data is read from files and reloaded on the next request whenever the export, tracker, or either log file changes. No restart is needed.
- No authentication. Anyone who can reach the API can record a decision under any name.
- No allow-list of deciders, because the sources disagree on who is allowed.
- `decided_at` for new decisions uses the server's local clock. The sample data has no time zones, so neither does the log.
- Decisions recorded here are not written back to the tracker spreadsheet, so the two can drift until someone reconciles them.
- The decision log is a local file and is not safe for several server processes at once. It is fine for a single-process prototype.
- A recorded decision cannot be changed or undone through the API.
- The approval email is sent from the dashboard, but replies are not read from the inbox. The user pastes the manager's reply. The per-ticket **Request Approval** on the Escalation Tracker page still only records the request and sends no email.
- There is one fixed user and one fixed manager, set in `.env`. Changing them needs a backend restart.
- The reply parser needs the ticket IDs in the reply. A manager who writes "approve all" with the original not quoted gets `422`.
- No notifications or Help Desk integration.
- The React frontend has an Escalation Tracker page (`/#/escalations`) and an Escalation Dashboard page (`/#/dashboard`). Other endpoints, such as `/escalations` and `/escalations/data-issues`, are only available through the API (`/docs`).

## Open questions for Mara

1. **Answered by the email round trip:** the fixed manager (`APPROVAL_MANAGER_NAME`) decides, and decisions from a reply are recorded under that name. The per-ticket decision endpoint still accepts any `decided_by`. Should it be restricted to the same manager?
2. Does `OK` in the tracker mean approved? The prototype assumes it does.
3. What should happen with `Need more info`? The prototype treats it as still pending.
4. In the tracker, is `approver` the person who decided, or the person who was asked?
5. Is "know the moment something is escalated" needed for the first version? If yes, by what channel?
6. **Answered by the email round trip:** managers reply to the approval email, and the user pastes the reply into the dashboard. Should the reply eventually be read from a shared inbox automatically?
7. Should decisions recorded here be written back to the tracker, or should the tracker eventually be replaced by this log?
8. Should a decision ever be changed after it is recorded?
9. What should happen to escalations still pending on tickets that are already resolved or closed?
11. Should `high` priority tickets also be included in the urgent-open analysis?
12. The 150 escalations and 600 tickets per week come from the discovery notes only. Are they current? File-based loading is fine at that volume, but it matters if the prototype grows.
