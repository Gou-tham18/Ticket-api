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
| Escalated tickets | Tags use `escalated`, `Escalated`, `ESCALATED`, `esc`, sometimes combined with `;vip` | All spellings are recognised. A ticket counts as escalated if it has an escalation tag or a tracker row. |
| Reuse supplied data | Tracker has one exact duplicate row (TCK-5111) and one row for a ticket not in the export (TCK-4999) | The duplicate is ignored, the orphan is not linked to anything, and both are listed at `/escalations/data-issues`. |
| "Know the moment something is escalated" (Mara's email) | Not in the Task 5 requirements; the scope excludes notifications unless confirmed | Not built. See open questions. |
| Managers "live in their email and will not learn a new tool" (Mara's email) | The Task 5 scope excludes email integration | Not built. The API is a building block; how managers would use it is an open question. |
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

Recorded decisions are appended to `data/decision_log.csv` (configurable with `DECISION_LOG_PATH`). The export and tracker files are never modified. The log is a plain CSV so it can be opened next to the existing spreadsheet, and it is reloaded on restart.

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

## Existing functionality

`/tickets`, `/summary`, `/triage`, the static page, and the frontend are unchanged. They still use `TICKETS_DATA_PATH` and `data/tickets_sample.csv`, which has a different schema from the Help Desk export. The original 18 tests pass without modification.

## Tests

`tests/test_escalations.py` adds 66 tests, for 84 in total. They cover decision and tag normalisation, day-first dates, open versus resolved status, joining the tracker to the export, duplicate and orphan handling, recording decisions, persistence across a restart, the source files staying untouched, every API error path, the urgent-open analysis, and manager approval requests. Four tests run against the supplied sample files and check the exact counts and issues listed above.

```
python -m pytest -q
```

## Limitations

- Data is read from files at startup. A new export or tracker file needs a restart.
- No authentication. Anyone who can reach the API can record a decision under any name.
- No allow-list of deciders, because the sources disagree on who is allowed.
- `decided_at` for new decisions uses the server's local clock. The sample data has no time zones, so neither does the log.
- Decisions recorded here are not written back to the tracker spreadsheet, so the two can drift until someone reconciles them.
- The decision log is a local file and is not safe for several server processes at once. It is fine for a single-process prototype.
- A recorded decision cannot be changed or undone through the API.
- No email, notifications, or Help Desk integration. Requesting approval records the request; it does not contact the manager.
- The React frontend has an Escalation Tracker page (`/#/escalations`) for the urgent-open analysis, approval requests, and decisions. Other endpoints, such as `/escalations` and `/escalations/data-issues`, are only available through the API (`/docs`).

## Open questions for Mara

1. Who is allowed to make the final decision: only Anil and Joyce, or also the six team members? Requests now go only to managers, but `decided_by` is still not restricted.
2. Does `OK` in the tracker mean approved? The prototype assumes it does.
3. What should happen with `Need more info`? The prototype treats it as still pending.
4. In the tracker, is `approver` the person who decided, or the person who was asked?
5. Is "know the moment something is escalated" needed for the first version? If yes, by what channel?
6. Since managers will not use a new tool, how should they record decisions? For example, a reply-by-email step that calls this API.
7. Should decisions recorded here be written back to the tracker, or should the tracker eventually be replaced by this log?
8. Should a decision ever be changed after it is recorded?
9. What should happen to escalations still pending on tickets that are already resolved or closed?
11. Should `high` priority tickets also be included in the urgent-open analysis?
12. The 150 escalations and 600 tickets per week come from the discovery notes only. Are they current? File-based loading is fine at that volume, but it matters if the prototype grows.
