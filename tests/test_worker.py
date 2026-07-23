from __future__ import annotations

from app.agent import AgentError, AgentNetworkError, CreatedTicket, Plan, PlannedTask
from app.alerts import MattermostAlerter
from app.database import Database
from app.security import hash_password
from app.worker import SubmissionWorker


class RecordingAgent:
    def __init__(self, fail_at: int | None = None):
        self.assignees = []
        self.fail_at = fail_at

    def plan(self, raw_input: str) -> Plan:
        assert raw_input == "첫 작업\n둘째 작업\n셋째 작업"
        return Plan(
            tasks=[PlannedTask(f"작업 {index}", None) for index in range(1, 4)],
            excluded=["완료된 메모"],
        )

    def create_task(
        self, task: PlannedTask, jira_account_id: str, sprint_id: int
    ) -> CreatedTicket:
        assert sprint_id == 50563
        self.assignees.append(jira_account_id)
        index = len(self.assignees)
        if self.fail_at == index:
            raise AgentError("synthetic Jira failure")
        return CreatedTicket(
            issue_key=f"S15P11A705-{100 + index}",
            summary=task.summary,
            url=f"https://ssafy.atlassian.net/browse/S15P11A705-{100 + index}",
        )


class RecordingAlerter(MattermostAlerter):
    def __init__(self):
        self.alerts = []

    def send_failure(self, **kwargs):
        self.alerts.append(kwargs)


def setup_submission(tmp_path, raw="첫 작업\n둘째 작업\n셋째 작업"):
    database = Database(tmp_path / "cowork.db")
    database.initialize()
    database.upsert_user(
        "member@example.com", hash_password("safe-password-123"), "김팀원", "jira-account-exact"
    )
    user = database.find_user("member@example.com")
    submission_id, _ = database.create_submission(
        "sub-1", user["id"], "idem-1", raw, 50563, "S15P11A7 1 스프린트 2"
    )
    return database, user, submission_id


def test_three_tasks_are_assigned_to_logged_in_user(tmp_path):
    database, user, submission_id = setup_submission(tmp_path)
    agent = RecordingAgent()
    alerter = RecordingAlerter()
    SubmissionWorker(database, agent, alerter).process(submission_id)

    result = database.get_submission(submission_id, user["id"])
    assert result["state"] == "completed"
    assert len(result["tickets"]) == 3
    assert agent.assignees == ["jira-account-exact"] * 3
    assert alerter.alerts == []


def test_partial_failure_keeps_successes_and_alerts_with_original_input(tmp_path):
    database, user, submission_id = setup_submission(tmp_path)
    agent = RecordingAgent(fail_at=2)
    alerter = RecordingAlerter()
    SubmissionWorker(database, agent, alerter).process(submission_id)

    result = database.get_submission(submission_id, user["id"])
    assert result["state"] == "partial"
    assert len(result["tickets"]) == 2
    assert result["public_message"] == "1개는 만들지 못했어요. 팀 리드에게 전달했습니다"
    assert len(alerter.alerts) == 1
    assert alerter.alerts[0]["raw_input"] == "첫 작업\n둘째 작업\n셋째 작업"
    assert alerter.alerts[0]["user_name"] == "김팀원"


def test_network_failure_uses_fixed_safe_message(tmp_path):
    database, user, submission_id = setup_submission(tmp_path)
    alerter = RecordingAlerter()

    class NetworkAgent:
        def plan(self, raw_input):
            raise AgentNetworkError("planner network failure: connection refused")

    SubmissionWorker(database, NetworkAgent(), alerter).process(submission_id)
    result = database.get_submission(submission_id, user["id"])
    assert result["state"] == "failed"
    assert result["public_message"] == "연결에 문제가 있어요. 다시 시도해주세요"
    assert len(alerter.alerts) == 1


def test_post_create_persistence_failure_requires_reconciliation(tmp_path, monkeypatch):
    database, user, submission_id = setup_submission(tmp_path)
    agent = RecordingAgent()
    alerter = RecordingAlerter()

    def fail_receipt(*args, **kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(database, "add_ticket", fail_receipt)
    SubmissionWorker(database, agent, alerter).process(submission_id)
    result = database.get_submission(submission_id, user["id"])
    assert result["state"] == "reconcile"
    assert result["tickets"] == []
    assert len(agent.assignees) == 1
    assert len(alerter.alerts) == 1


def test_failed_mattermost_delivery_is_durably_queued(tmp_path):
    database, user, submission_id = setup_submission(tmp_path)

    class FailingAgent:
        def plan(self, raw_input):
            raise AgentError("synthetic planner failure")

    class FailingAlerter:
        def send_failure(self, **kwargs):
            raise OSError("synthetic Mattermost failure")

    worker = SubmissionWorker(database, FailingAgent(), FailingAlerter())
    worker.process(submission_id)
    assert len(database.list_pending_alerts()) == 1

    successful_alerter = RecordingAlerter()
    worker.alerter = successful_alerter
    worker.flush_pending_alerts()
    assert database.list_pending_alerts() == []
    assert len(successful_alerter.alerts) == 1
