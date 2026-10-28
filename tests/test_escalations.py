import csv
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.escalations import (
    AlreadyDecided,
    EscalationService,
    NotAnEscalation,
    TicketNotFound,
    is_escalation_tag_set,
    normalise_decision,
)
from app.main import app, get_escalation_service

SAMPLE_EXPORT = Path("data/helpdesk_export_sample.csv")
SAMPLE_TRACKER = Path("data/escalation_tracker_sample.csv")

EXPORT_HEADER = (
    "ticket_id,created_at,category,priority,status,"
    "requester_email,assigned_to,tags,refund_amount\n"
)
TRACKER_HEADER = "ticket_id,requested_by,approver,requested_at,decision,decided_at,notes\n"

FIXED_NOW = datetime(2026, 10, 20, 9, 15, 42)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path):
    export = write(
        tmp_path / "export.csv",
        EXPORT_HEADER
        + "TCK-1,2026-10-05 13:05,Billing,urgent,open,a@x.com,riya,escalated,480\n"
        + "TCK-2,2026-10-05 14:00,Login,normal,in_progress,b@x.com,sam,,\n"
        + "TCK-3,2026-10-05 15:00,Billing,high,resolved,c@x.com,ken,ESC;vip,20\n"
        + "TCK-4,2026-10-05 16:00,Refunds,normal,open,d@x.com,lia,Escalated,\n"
        + "TCK-5,2026-10-05 17:00,Technical,low,closed,e@x.com,tom,,\n"
        + "TCK-6,2026-10-05 18:00,Billing,normal,open,f@x.com,zoe,esc,\n",
    )
    tracker = write(
        tmp_path / "tracker.csv",
        TRACKER_HEADER
        + "TCK-1,Riya,Joyce,2026-10-05 15:00,OK,06/10/2026 00:05,chased twice\n"
        + "TCK-3,Sam,Anil,2026-10-05 16:00,Rejected,2026-10-05 18:00,\n"
        + "TCK-4,Zoe,Anil,2026-10-05 17:00,Need more info,2026-10-05 19:00,\n"
        + "TCK-4,Zoe,Anil,2026-10-05 17:00,Need more info,2026-10-05 19:00,\n"
        + "TCK-9,Tom,Anil,2026-10-05 09:00,Approved,2026-10-05 10:00,not in export\n",
    )
    return export, tracker, tmp_path / "decisions.csv"


@pytest.fixture
def service(files):
    export, tracker, log = files
    return EscalationService(export, tracker, log, clock=lambda: FIXED_NOW)


@pytest.fixture
def client(service):
    app.dependency_overrides[get_escalation_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.clear()


# Normalising the tracker's messy values ------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("approved", "Accept"),
        ("Approved", "Accept"),
        ("OK", "Accept"),
        ("rejected", "Reject"),
        ("Rejected", "Reject"),
        ("Need more info", None),
        ("", None),
    ],
)
def test_tracker_decisions_map_to_accept_or_reject(raw, expected):
    assert normalise_decision(raw) == expected


@pytest.mark.parametrize(
    "tags, expected",
    [
        ("escalated", True),
        ("ESCALATED", True),
        ("esc", True),
        ("Escalated;vip", True),
        ("esc;vip", True),
        ("vip", False),
        ("team-account", False),
        ("", False),
    ],
)
def test_escalation_tag_spellings(tags, expected):
    assert is_escalation_tag_set(tags) is expected


def test_day_first_tracker_dates_are_read_correctly(service):
    escalation = service.ticket_view("TCK-1")["escalation"]

    # 06/10/2026 is 6 October (requested on 5 October), not 10 June.
    assert escalation["decided_at"] == "2026-10-06 00:05"


# Ticket details ----------------------------------------------------------


def test_ticket_view_shows_required_details(service):
    view = service.ticket_view("TCK-2")

    assert view["ticket_id"] == "TCK-2"
    assert view["category"] == "Login"
    assert view["priority"] == "normal"
    assert view["created_at"] == "2026-10-05 14:00"
    assert view["status"] == "in_progress"
    assert view["escalation"] is None


def test_open_and_in_progress_count_as_open_resolved_and_closed_do_not(service):
    assert service.ticket_view("TCK-1")["is_open"] is True
    assert service.ticket_view("TCK-2")["is_open"] is True
    assert service.ticket_view("TCK-3")["is_open"] is False
    assert service.ticket_view("TCK-5")["is_open"] is False


def test_unknown_ticket_raises(service):
    with pytest.raises(TicketNotFound):
        service.ticket_view("TCK-404")


# Joining the tracker to the export ----------------------------------------


def test_tracker_decision_is_associated_with_its_ticket(service):
    escalation = service.ticket_view("TCK-3")["escalation"]

    assert escalation["decision"] == "Reject"
    assert escalation["state"] == "rejected"
    assert escalation["decision_source"] == "tracker"
    assert escalation["decided_by"] == "Anil"


def test_need_more_info_is_pending_and_keeps_raw_value(service):
    escalation = service.ticket_view("TCK-4")["escalation"]

    assert escalation["state"] == "pending"
    assert escalation["decision"] is None
    assert escalation["decided_at"] is None
    assert escalation["tracker_decision_raw"] == "Need more info"


def test_tagged_ticket_without_tracker_row_is_pending(service):
    escalation = service.ticket_view("TCK-6")["escalation"]

    assert escalation["in_tracker"] is False
    assert escalation["state"] == "pending"


def test_data_issues_report_duplicates_and_orphans(service):
    problems = {(i["ticket_id"], i["problem"]) for i in service.issues}

    assert ("TCK-4", "exact duplicate row ignored") in problems
    assert (
        "TCK-9",
        "ticket is not in the Help Desk export; row ignored",
    ) in problems


def test_conflicting_duplicate_keeps_first_row(files):
    export, _, log = files
    tracker = write(
        files[2].parent / "conflict.csv",
        TRACKER_HEADER
        + "TCK-1,Riya,Joyce,2026-10-05 15:00,Approved,2026-10-05 16:00,\n"
        + "TCK-1,Riya,Joyce,2026-10-05 15:00,Rejected,2026-10-05 17:00,\n",
    )
    service = EscalationService(export, tracker, log)

    assert service.ticket_view("TCK-1")["escalation"]["decision"] == "Accept"
    assert any("conflicting duplicate" in i["problem"] for i in service.issues)


def test_unrecognised_decision_is_pending_and_reported(files):
    export, _, log = files
    tracker = write(
        files[2].parent / "odd.csv",
        TRACKER_HEADER + "TCK-1,Riya,Joyce,2026-10-05 15:00,maybe,,\n",
    )
    service = EscalationService(export, tracker, log)

    assert service.ticket_view("TCK-1")["escalation"]["state"] == "pending"
    assert any("unrecognised decision" in i["problem"] for i in service.issues)


# Recording decisions -------------------------------------------------------


def test_record_decision_stores_who_and_when(service):
    view = service.record_decision("TCK-4", "Accept", "Joyce")
    escalation = view["escalation"]

    assert escalation["decision"] == "Accept"
    assert escalation["decided_by"] == "Joyce"
    assert escalation["decided_at"] == "2026-10-20 09:15"
    assert escalation["decision_source"] == "prototype"


def test_record_decision_is_appended_to_log_not_to_source_files(files, service):
    export, tracker, log = files
    tracker_before = tracker.read_text(encoding="utf-8")
    export_before = export.read_text(encoding="utf-8")

    service.record_decision("TCK-6", "Reject", "Anil")

    assert tracker.read_text(encoding="utf-8") == tracker_before
    assert export.read_text(encoding="utf-8") == export_before
    with open(log, newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert rows == [
        {
            "ticket_id": "TCK-6",
            "decision": "Reject",
            "decided_by": "Anil",
            "decided_at": "2026-10-20 09:15",
        }
    ]


def test_recorded_decisions_survive_a_restart(files, service):
    export, tracker, log = files
    service.record_decision("TCK-6", "Reject", "Anil")

    reloaded = EscalationService(export, tracker, log)

    assert reloaded.ticket_view("TCK-6")["escalation"]["decision"] == "Reject"


def test_cannot_overwrite_a_final_decision(service):
    with pytest.raises(AlreadyDecided):
        service.record_decision("TCK-1", "Reject", "Anil")


def test_cannot_decide_a_ticket_that_is_not_escalated(service):
    with pytest.raises(NotAnEscalation):
        service.record_decision("TCK-2", "Accept", "Anil")


def test_decision_must_be_accept_or_reject(service):
    with pytest.raises(ValueError):
        service.record_decision("TCK-4", "Need more info", "Anil")


# API -----------------------------------------------------------------------


def test_api_lists_open_tickets_only(client):
    body = client.get("/helpdesk/tickets", params={"open_only": "true"}).json()

    assert {t["ticket_id"] for t in body} == {"TCK-1", "TCK-2", "TCK-4", "TCK-6"}


def test_api_filters_by_category_case_insensitively(client):
    body = client.get("/helpdesk/tickets", params={"category": "billing"}).json()

    assert {t["ticket_id"] for t in body} == {"TCK-1", "TCK-3", "TCK-6"}


def test_api_lists_pending_escalations(client):
    body = client.get("/escalations", params={"state": "pending"}).json()

    assert {t["ticket_id"] for t in body} == {"TCK-4", "TCK-6"}


def test_api_rejects_unknown_state_filter(client):
    assert client.get("/escalations", params={"state": "maybe"}).status_code == 422


def test_api_records_decision(client):
    response = client.post(
        "/escalations/TCK-4/decision",
        json={"decision": "Reject", "decided_by": "Anil"},
    )

    assert response.status_code == 200
    assert response.json()["escalation"]["state"] == "rejected"
    pending = client.get("/escalations", params={"state": "pending"}).json()
    assert {t["ticket_id"] for t in pending} == {"TCK-6"}


@pytest.mark.parametrize(
    "ticket_id, payload, status",
    [
        ("TCK-404", {"decision": "Accept", "decided_by": "Anil"}, 404),
        ("TCK-2", {"decision": "Accept", "decided_by": "Anil"}, 409),
        ("TCK-1", {"decision": "Reject", "decided_by": "Anil"}, 409),
        ("TCK-4", {"decision": "approved", "decided_by": "Anil"}, 422),
        ("TCK-4", {"decision": "Accept", "decided_by": "   "}, 422),
        ("TCK-4", {"decision": "Accept"}, 422),
    ],
)
def test_api_decision_errors(client, ticket_id, payload, status):
    response = client.post(f"/escalations/{ticket_id}/decision", json=payload)

    assert response.status_code == status


def test_api_unknown_helpdesk_ticket_is_404(client):
    assert client.get("/helpdesk/tickets/TCK-404").status_code == 404


def test_api_reports_data_issues(client):
    body = client.get("/escalations/data-issues").json()

    assert {"TCK-4", "TCK-9"} <= {issue["ticket_id"] for issue in body}


# Supplied sample files -----------------------------------------------------


@pytest.fixture
def sample_service(tmp_path):
    return EscalationService(SAMPLE_EXPORT, SAMPLE_TRACKER, tmp_path / "log.csv")


def test_sample_files_load_all_tickets(sample_service):
    assert len(sample_service.tickets) == 120


def test_sample_tracker_issues_are_reported(sample_service):
    problems = {(i["ticket_id"], i["problem"]) for i in sample_service.issues}

    assert problems == {
        ("TCK-4999", "ticket is not in the Help Desk export; row ignored"),
        ("TCK-5111", "exact duplicate row ignored"),
    }


def test_sample_escalation_states(sample_service):
    def count(state):
        return len(sample_service.list_escalations(state=state))

    # 34 escalated tickets: 28 tracker rows plus 6 tagged with no tracker row.
    assert count("accepted") == 14
    assert count("rejected") == 5
    assert count("pending") == 15
    assert count(None) == 34


# Urgent open tickets and manager approval ----------------------------------

from app.escalations import AlreadyRequested, UnknownManager  # noqa: E402

URGENT_NOW = datetime(2026, 10, 6, 12, 0)


@pytest.fixture
def urgent_service(tmp_path):
    export = write(
        tmp_path / "export.csv",
        EXPORT_HEADER
        # urgent, open, no escalation at all -> not_requested
        + "U-1,2026-10-05 08:00,Billing,urgent,open,a@x.com,riya,,\n"
        # urgent, in_progress, tagged but no tracker row -> not_requested
        + "U-2,2026-10-05 09:00,Shipping,urgent,in_progress,b@x.com,sam,esc,\n"
        # urgent, open, in tracker without decision -> awaiting_decision
        + "U-3,2026-10-05 10:00,Billing,urgent,open,c@x.com,ken,escalated,\n"
        # urgent, open, accepted
        + "U-4,2026-10-05 11:00,Refunds,urgent,open,d@x.com,lia,escalated,\n"
        # urgent but resolved -> excluded
        + "U-5,2026-10-05 12:00,Billing,urgent,resolved,e@x.com,tom,escalated,\n"
        # open but not urgent -> excluded
        + "U-6,2026-10-05 13:00,Billing,high,open,f@x.com,zoe,,\n",
    )
    tracker = write(
        tmp_path / "tracker.csv",
        TRACKER_HEADER
        + "U-3,Riya,Anil,2026-10-06 06:00,,,\n"
        + "U-4,Lia,Joyce,2026-10-05 12:00,approved,2026-10-05 13:00,\n"
        + "U-5,Tom,Joyce,2026-10-05 13:00,,,\n",
    )
    return EscalationService(
        export, tracker, tmp_path / "decisions.csv", clock=lambda: URGENT_NOW
    )


@pytest.fixture
def urgent_client(urgent_service):
    app.dependency_overrides[get_escalation_service] = lambda: urgent_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_analysis_includes_only_urgent_open_tickets(urgent_service):
    result = urgent_service.urgent_open_analysis()

    assert {t["ticket_id"] for t in result["tickets"]} == {"U-1", "U-2", "U-3", "U-4"}
    assert result["total"] == 4


def test_analysis_groups_by_approval_stage(urgent_service):
    result = urgent_service.urgent_open_analysis()
    stages = {t["ticket_id"]: t["approval_stage"] for t in result["tickets"]}

    assert stages == {
        "U-1": "not_requested",
        "U-2": "not_requested",
        "U-3": "awaiting_decision",
        "U-4": "accepted",
    }
    assert result["by_stage"] == {
        "not_requested": 2,
        "awaiting_decision": 1,
        "accepted": 1,
        "rejected": 0,
    }
    assert result["needs_action"] == 3


def test_analysis_lists_tickets_needing_action_first_oldest_first(urgent_service):
    order = [t["ticket_id"] for t in urgent_service.urgent_open_analysis()["tickets"]]

    assert order == ["U-1", "U-2", "U-3", "U-4"]


def test_analysis_reports_ages(urgent_service):
    tickets = {t["ticket_id"]: t for t in urgent_service.urgent_open_analysis()["tickets"]}

    assert tickets["U-1"]["age_hours"] == 28.0
    assert tickets["U-3"]["waiting_for_decision_hours"] == 6.0
    assert tickets["U-4"]["waiting_for_decision_hours"] is None


def test_analysis_filters(urgent_service):
    billing = urgent_service.urgent_open_analysis(category="billing")
    in_progress = urgent_service.urgent_open_analysis(status="in_progress")

    assert {t["ticket_id"] for t in billing["tickets"]} == {"U-1", "U-3"}
    assert {t["ticket_id"] for t in in_progress["tickets"]} == {"U-2"}


def test_managers_default_to_tracker_approvers(urgent_service):
    assert urgent_service.managers == ["Anil", "Joyce"]


def test_request_approval_moves_ticket_to_awaiting_decision(urgent_service):
    urgent_service.request_approval("U-1", "Riya", "joyce")

    ticket = next(
        t for t in urgent_service.urgent_open_analysis()["tickets"] if t["ticket_id"] == "U-1"
    )
    assert ticket["approval_stage"] == "awaiting_decision"
    assert ticket["escalation"]["approver"] == "Joyce"
    assert ticket["escalation"]["requested_at"] == "2026-10-06 12:00"
    assert ticket["escalation"]["request_source"] == "prototype"


def test_requested_ticket_can_then_be_decided(urgent_service):
    urgent_service.request_approval("U-1", "Riya", "Anil")
    view = urgent_service.record_decision("U-1", "Accept", "Anil")

    assert view["escalation"]["state"] == "accepted"


def test_approval_requests_survive_a_restart(urgent_service):
    urgent_service.request_approval("U-2", "Sam", "Anil")

    reloaded = EscalationService(
        urgent_service.export_path,
        urgent_service.tracker_path,
        urgent_service.decision_log_path,
    )

    assert reloaded.ticket_view("U-2")["escalation"]["approver"] == "Anil"


def test_request_approval_rules(urgent_service):
    with pytest.raises(UnknownManager):
        urgent_service.request_approval("U-1", "Riya", "Mara")
    with pytest.raises(AlreadyRequested):
        urgent_service.request_approval("U-3", "Riya", "Anil")
    with pytest.raises(TicketNotFound):
        urgent_service.request_approval("U-404", "Riya", "Anil")
    with pytest.raises(ValueError):
        urgent_service.request_approval("U-1", "  ", "Anil")


def test_api_urgent_open_analysis(urgent_client):
    body = urgent_client.get("/approvals/urgent-open").json()

    assert body["needs_action"] == 3
    assert body["managers"] == ["Anil", "Joyce"]


def test_api_rejects_closed_status_filter(urgent_client):
    response = urgent_client.get("/approvals/urgent-open", params={"status": "resolved"})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "ticket_id, payload, status",
    [
        ("U-1", {"requested_by": "Riya", "approver": "Anil"}, 200),
        ("U-1", {"requested_by": "Riya", "approver": "Mara"}, 422),
        ("U-1", {"requested_by": "   ", "approver": "Anil"}, 422),
        ("U-1", {"requested_by": "Riya"}, 422),
        ("U-3", {"requested_by": "Riya", "approver": "Anil"}, 409),
        ("U-404", {"requested_by": "Riya", "approver": "Anil"}, 404),
    ],
)
def test_api_request_approval(urgent_client, ticket_id, payload, status):
    response = urgent_client.post(f"/approvals/{ticket_id}/request", json=payload)

    assert response.status_code == status


def test_sample_urgent_open_analysis(sample_service):
    result = sample_service.urgent_open_analysis()
    stages = {t["ticket_id"]: t["approval_stage"] for t in result["tickets"]}

    assert result["total"] == 10
    assert result["by_stage"] == {
        "not_requested": 2,
        "awaiting_decision": 2,
        "accepted": 6,
        "rejected": 0,
    }
    assert {k for k, v in stages.items() if v == "not_requested"} == {"TCK-5070", "TCK-5110"}
    assert {k for k, v in stages.items() if v == "awaiting_decision"} == {"TCK-5007", "TCK-5050"}
