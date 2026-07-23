from __future__ import annotations

import json
import os
import subprocess

import pytest

from app.agent import (
    AgentError,
    AgentReconciliationRequired,
    HermesJiraAgent,
    PlannedTask,
    _parse_plan_payload,
)
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
                        "source_indices": [0, 1],
                        "summary": "카카오페이 결제 연동 완료",
                        "description": None,
                    },
                    {
                        "source_indices": [0],
                        "summary": "결제 오류 로그 확인",
                        "description": "실패 케이스를 확인한다",
                    },
                ],
                "excluded": [{"source_index": 2, "text": "2시 회의"}],
            }
        ),
    )
    plan = HermesJiraAgent(settings(tmp_path)).plan(
        "작업\n실패 케이스를 확인한다\n2시 회의"
    )
    assert [task.summary for task in plan.tasks] == [
        "카카오페이 결제 연동 완료",
        "결제 오류 로그 확인",
    ]
    assert plan.tasks[0].description == "작업\n실패 케이스를 확인한다"
    assert plan.tasks[1].description == "실패 케이스를 확인한다"
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
                    {"source_indices": [0], "summary": "첫 작업", "description": None}
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
                    "source_indices": [0],
                    "summary": "로그인 오류 재현",
                    "description": None,
                }
            ),
            completed(
                {
                    "tasks": [
                        {
                            "source_indices": [0],
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


@pytest.mark.parametrize("source_indices", [[[0]], [True], [0, 0]])
def test_planner_rejects_malformed_source_indices(source_indices):
    payload = {
        "tasks": [
            {
                "source_indices": source_indices,
                "summary": "로그인 오류 재현",
                "description": None,
            }
        ],
        "excluded": [],
    }
    with pytest.raises(AgentError, match="invalid planned source indices"):
        _parse_plan_payload(payload, ["로그인 오류 재현"])


def test_planner_accepts_structured_input_over_twenty_lines(monkeypatch, tmp_path):
    source_lines = [f"상세 내용 {index}" for index in range(21)]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: completed(
            {
                "tasks": [
                    {
                        "source_indices": list(range(21)),
                        "summary": "구조화 작업 처리",
                        "description": None,
                    }
                ],
                "excluded": [],
            }
        ),
    )

    plan = HermesJiraAgent(settings(tmp_path)).plan("\n".join(source_lines))

    assert len(plan.tasks) == 1
    assert plan.tasks[0].description == "\n".join(source_lines)


def test_creator_calls_only_direct_mcp_bridge_with_fixed_fields(monkeypatch, tmp_path):
    agent = HermesJiraAgent(settings(tmp_path))
    task = PlannedTask("결제 연동 완료", None)
    observed = {}

    def success(command, **kwargs):
        observed["command"] = command
        observed["request"] = json.loads(kwargs["input"])
        return bridge_completed({"issue_key": "S15P11A705-10"})

    monkeypatch.setattr(subprocess, "run", success)
    ticket = agent.create_task(task, "account-id", 50563, "Infra")
    assert ticket.issue_key == "S15P11A705-10"
    assert observed["command"][0] == agent.settings.hermes_python
    assert observed["command"][1:] == ["-m", "app.mcp_create_bridge"]
    assert observed["request"] == {
        "cloudId": "https://ssafy.atlassian.net",
        "projectKey": "S15P11A705",
        "issueTypeName": "Task",
        "summary": "[Infra] 결제 연동 완료",
        "assignee_account_id": "account-id",
        "contentFormat": "markdown",
        "additional_fields": {
            "customfield_10020": 50563,
            "labels": ["Infra"],
        },
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: bridge_completed({"issue_key": "OTHER-10"}),
    )
    with pytest.raises(AgentError):
        agent.create_task(task, "account-id", 50563, "Infra")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: bridge_completed({"error": "synthetic"}, returncode=1),
    )
    with pytest.raises(AgentError, match="synthetic"):
        agent.create_task(task, "account-id", 50563, "Infra")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: bridge_completed(
            {"error": "post_create_ambiguous"}, returncode=42
        ),
    )
    with pytest.raises(AgentReconciliationRequired):
        agent.create_task(task, "account-id", 50563, "Infra")


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
