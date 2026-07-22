import json
import subprocess

import pytest

from app.config import Settings
from app.seed_user import lookup_account_id


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


def test_lookup_uses_direct_read_only_bridge(monkeypatch, tmp_path):
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["request"] = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps({"account_id": "synthetic-account-id"}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    value = lookup_account_id(settings(tmp_path), "김팀원")
    assert value == "synthetic-account-id"
    assert observed["command"][1:] == ["-m", "app.mcp_lookup_bridge"]
    assert observed["request"] == {
        "cloudId": "https://ssafy.atlassian.net",
        "displayName": "김팀원",
    }


def test_lookup_rejects_invalid_response(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"error": "not found"}), stderr=""
        ),
    )
    with pytest.raises(RuntimeError):
        lookup_account_id(settings(tmp_path), "없는 사용자")
