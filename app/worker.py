from __future__ import annotations

import logging

from .agent import (
    AgentNetworkError,
    AgentReconciliationRequired,
    AgentTimeout,
    HermesJiraAgent,
    Plan,
    PlannedTask,
)
from .alerts import MattermostAlerter
from .database import Database

logger = logging.getLogger(__name__)

GENERIC_FAILURE = "지금 티켓을 만들 수 없어요. 팀 리드에게 전달했습니다"
TIMEOUT_FAILURE = "시간이 오래 걸리고 있어요. 잠시 후 다시 시도해주세요"
NETWORK_FAILURE = "연결에 문제가 있어요. 다시 시도해주세요"


class SubmissionWorker:
    def __init__(self, database: Database, agent: HermesJiraAgent, alerter: MattermostAlerter):
        self.database = database
        self.agent = agent
        self.alerter = alerter

    def _alert(self, *, error: str, raw_input: str, user_name: str) -> str:
        try:
            self.alerter.send_failure(error=error, raw_input=raw_input, user_name=user_name)
            return error
        except Exception as alert_error:
            try:
                self.database.enqueue_alert(
                    error=error, raw_input=raw_input, user_name=user_name
                )
            except Exception:
                logger.critical("Failure alert could not be queued")
            logger.critical("Mattermost failure alert could not be delivered")
            return f"{error}; alert_delivery_failed={type(alert_error).__name__}"

    def flush_pending_alerts(self) -> None:
        for alert in self.database.list_pending_alerts():
            try:
                self.alerter.send_failure(
                    error=alert["error_text"],
                    raw_input=alert["raw_input"],
                    user_name=alert["user_name"],
                )
            except Exception:
                self.database.record_alert_attempt(alert["id"], delivered=False)
                logger.critical("Queued Mattermost alert could not be delivered")
            else:
                self.database.record_alert_attempt(alert["id"], delivered=True)

    def prepare(self, submission_id: str) -> None:
        self.flush_pending_alerts()
        submission = self.database.get_submission_for_worker(submission_id)
        if not submission:
            return
        raw_input = submission["raw_input"]
        user_name = submission["display_name"]
        self.database.update_submission(submission_id, "organizing")
        try:
            plan = self.agent.plan(raw_input)
        except AgentTimeout as exc:
            detail = self._alert(error=str(exc), raw_input=raw_input, user_name=user_name)
            self.database.update_submission(
                submission_id, "failed", public_message=TIMEOUT_FAILURE, internal_error=detail
            )
            return
        except AgentNetworkError as exc:
            detail = self._alert(error=str(exc), raw_input=raw_input, user_name=user_name)
            self.database.update_submission(
                submission_id, "failed", public_message=NETWORK_FAILURE, internal_error=detail
            )
            return
        except Exception as exc:
            detail = self._alert(error=str(exc), raw_input=raw_input, user_name=user_name)
            self.database.update_submission(
                submission_id, "failed", public_message=GENERIC_FAILURE, internal_error=detail
            )
            return

        if not plan.tasks:
            detail = self._alert(
                error="planner found no actionable task", raw_input=raw_input, user_name=user_name
            )
            self.database.update_submission(
                submission_id,
                "failed",
                public_message=GENERIC_FAILURE,
                excluded=plan.excluded,
                internal_error=detail,
            )
            return

        try:
            self.database.save_plan(
                submission_id,
                [
                    {"summary": task.summary, "description": task.description}
                    for task in plan.tasks
                ],
                plan.excluded,
            )
        except Exception as exc:
            detail = self._alert(
                error=f"preview persistence failed: {type(exc).__name__}",
                raw_input=raw_input,
                user_name=user_name,
            )
            self.database.update_submission(
                submission_id,
                "failed",
                public_message=GENERIC_FAILURE,
                internal_error=detail,
            )

    def create(self, submission_id: str) -> None:
        self.flush_pending_alerts()
        submission = self.database.get_submission_for_worker(submission_id)
        if not submission or submission["state"] != "creating":
            return
        raw_input = submission["raw_input"]
        user_name = submission["display_name"]
        plan = Plan(
            tasks=[PlannedTask(**task) for task in submission["planned_tasks"]],
            excluded=submission["excluded"],
        )
        if not plan.tasks:
            detail = self._alert(
                error="confirmed submission has no planned tasks",
                raw_input=raw_input,
                user_name=user_name,
            )
            self.database.update_submission(
                submission_id,
                "failed",
                public_message=GENERIC_FAILURE,
                internal_error=detail,
            )
            return

        failures: list[str] = []
        timed_out = False
        for task in plan.tasks:
            try:
                ticket = self.agent.create_task(task, submission["jira_account_id"])
            except AgentReconciliationRequired as exc:
                detail = self._alert(
                    error=str(exc), raw_input=raw_input, user_name=user_name
                )
                self.database.update_submission(
                    submission_id,
                    "reconcile",
                    public_message=GENERIC_FAILURE,
                    excluded=plan.excluded,
                    internal_error=detail,
                )
                return
            except AgentTimeout as exc:
                timed_out = True
                failures.append(str(exc))
                break
            except AgentNetworkError as exc:
                failures.append(str(exc))
                break
            except Exception as exc:
                failures.append(str(exc))
                continue
            try:
                self.database.add_ticket(
                    submission_id, ticket.issue_key, ticket.summary, ticket.url
                )
            except Exception as exc:
                detail = self._alert(
                    error=f"post-create receipt persistence failed: {type(exc).__name__}",
                    raw_input=raw_input,
                    user_name=user_name,
                )
                self.database.update_submission(
                    submission_id,
                    "reconcile",
                    public_message=GENERIC_FAILURE,
                    excluded=plan.excluded,
                    internal_error=detail,
                )
                return

        if failures:
            detail = self._alert(
                error=" | ".join(failures), raw_input=raw_input, user_name=user_name
            )
            successful = self.database.get_submission(submission_id, submission["user_id"])
            success_count = len(successful["tickets"]) if successful else 0
            failed_count = len(plan.tasks) - success_count
            if success_count:
                self.database.update_submission(
                    submission_id,
                    "partial",
                    public_message=f"{failed_count}개는 만들지 못했어요. 팀 리드에게 전달했습니다",
                    excluded=plan.excluded,
                    internal_error=detail,
                )
            else:
                network_failed = any("network failure" in failure for failure in failures)
                message = (
                    TIMEOUT_FAILURE
                    if timed_out
                    else NETWORK_FAILURE if network_failed else GENERIC_FAILURE
                )
                self.database.update_submission(
                    submission_id,
                    "failed",
                    public_message=message,
                    excluded=plan.excluded,
                    internal_error=detail,
                )
            return

        self.database.update_submission(
            submission_id, "completed", excluded=plan.excluded
        )

    def process(self, submission_id: str) -> None:
        """Backward-compatible one-shot path used by worker-level tests."""
        self.prepare(submission_id)
        submission = self.database.get_submission_for_worker(submission_id)
        if not submission or not submission["planned_tasks"]:
            return
        self.database.update_submission(
            submission_id, "creating", excluded=submission["excluded"]
        )
        self.create(submission_id)

    def recover_inflight(self) -> None:
        self.flush_pending_alerts()
        for submission in self.database.list_inflight_submissions():
            detail = self._alert(
                error="server restarted before submission completed",
                raw_input=submission["raw_input"],
                user_name=submission["display_name"],
            )
            self.database.update_submission(
                submission["id"],
                "reconcile" if submission["state"] == "creating" else "failed",
                public_message=GENERIC_FAILURE,
                internal_error=detail,
            )
