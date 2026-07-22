from __future__ import annotations

import json
import os
import subprocess

import pytest

from app.agent import AgentError, AgentReconciliationRequired, HermesJiraAgent, PlannedTask
from app.config import Settings


def settings(tmp_path):
    return Settings(
        project_key="S15P11A705",
        jira_base_url="https://ssafy.atlassian.net",
        database_path=tmp_path / "db",
        cookie_secure=False,
        agent_timeout_seconds=60,
        mattermost_webhook_url=None,
        hermes_command="hermes",
    )


def completed(payload):
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout="session_id: synthetic\n" + json.dumps(payload), stderr=""
    )


def bridge_completed(payload, returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=json.dumps(payload), stderr=""
    )


def test_planner_accepts_only_closed_json(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: completed(
            {
                "tasks": [
                    {
                        "source_index": 0,
                        "summary": "카카오페이 결제 연동 완료",
                        "description": None,
                    },
                    {
                        "source_index": 0,
                        "summary": "결제 오류 로그 확인",
                        "description": "실패 케이스를 확인한다",
                    },
                ],
                "excluded": [{"source_index": 1, "text": "2시 회의"}],
            }
        ),
    )
    plan = HermesJiraAgent(settings(tmp_path)).plan("작업\n2시 회의")
    assert [task.summary for task in plan.tasks] == [
        "카카오페이 결제 연동 완료",
        "결제 오류 로그 확인",
    ]
    assert plan.excluded == ["2시 회의"]

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: completed({"tasks": [], "excluded": [], "private": "x"}),
    )
    with pytest.raises(AgentError):
        HermesJiraAgent(settings(tmp_path)).plan("작업")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: completed(
            {
                "tasks": [
                    {"source_index": 0, "summary": "첫 작업", "description": None}
                ],
                "excluded": [],
            }
        ),
    )
    with pytest.raises(AgentError, match="dropped input lines"):
        HermesJiraAgent(settings(tmp_path)).plan("첫 작업\n둘째 작업")


def test_planner_retries_once_after_schema_mismatch(monkeypatch, tmp_path):
    responses = iter(
        [
            completed(
                {
                    "source_index": 0,
                    "summary": "로그인 오류 재현",
                    "description": None,
                }
            ),
            completed(
                {
                    "tasks": [
                        {
                            "source_index": 0,
                            "summary": "로그인 오류 재현",
                            "description": None,
                        }
                    ],
                    "excluded": [],
                }
            ),
        ]
    )
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs["input"])
        return next(responses)

    monkeypatch.setattr(subprocess, "run", fake_run)
    plan = HermesJiraAgent(settings(tmp_path)).plan("로그인 오류 재현하기")

    assert [task.summary for task in plan.tasks] == ["로그인 오류 재현"]
    assert len(calls) == 2
    assert "schema correction retry" in calls[1]


def test_creator_calls_only_direct_mcp_bridge_with_fixed_fields(monkeypatch, tmp_path):
    agent = HermesJiraAgent(settings(tmp_path))
    task = PlannedTask("결제 연동 완료", None)
    observed = {}

    def success(command, **kwargs):
        observed["command"] = command
        observed["request"] = json.loads(kwargs["input"])
        return bridge_completed({"issue_key": "S15P11A705-10"})

    monkeypatch.setattr(subprocess, "run", success)
    ticket = agent.create_task(task, "account-id")
    assert ticket.issue_key == "S15P11A705-10"
    assert observed["command"][0] == agent.settings.hermes_python
    assert observed["command"][1:] == ["-m", "app.mcp_create_bridge"]
    assert observed["request"] == {
        "cloudId": "https://ssafy.atlassian.net",
        "projectKey": "S15P11A705",
        "issueTypeName": "Task",
        "summary": "결제 연동 완료",
        "assignee_account_id": "account-id",
        "contentFormat": "markdown",
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: bridge_completed({"issue_key": "OTHER-10"}),
    )
    with pytest.raises(AgentError):
        agent.create_task(task, "account-id")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: bridge_completed({"error": "synthetic"}, returncode=1),
    )
    with pytest.raises(AgentError, match="synthetic"):
        agent.create_task(task, "account-id")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: bridge_completed(
            {"error": "post_create_ambiguous"}, returncode=42
        ),
    )
    with pytest.raises(AgentReconciliationRequired):
        agent.create_task(task, "account-id")


def test_agent_passes_prompts_as_single_argument_without_shell(monkeypatch, tmp_path):
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return completed(
            {
                "tasks": [],
                "excluded": [
                    {
                        "source_index": 0,
                        "text": "$(touch /tmp/should-not-exist)",
                    }
                ],
            }
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    HermesJiraAgent(settings(tmp_path)).plan("$(touch /tmp/should-not-exist)")
    assert observed["kwargs"].get("shell") is None
    assert isinstance(observed["command"], list)
    assert "$(touch /tmp/should-not-exist)" not in " ".join(observed["command"])
    assert "$(touch /tmp/should-not-exist)" in observed["kwargs"]["input"]
    assert not os.path.exists("/tmp/should-not-exist")
