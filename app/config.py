from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_key: str
    jira_base_url: str
    database_path: Path
    cookie_secure: bool
    agent_timeout_seconds: int
    mattermost_webhook_url: str | None
    hermes_command: str
    hermes_python: str = "/usr/local/lib/hermes-agent/venv/bin/python"

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("COWORK_ENV", "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise RuntimeError("COWORK_ENV must be development, test, or production")
        project_key = os.getenv("JIRA_PROJECT_KEY", "").strip()
        if not project_key:
            raise RuntimeError("JIRA_PROJECT_KEY is required")
        timeout = int(os.getenv("COWORK_AGENT_TIMEOUT_SECONDS", "60"))
        if timeout < 10 or timeout > 180:
            raise RuntimeError("COWORK_AGENT_TIMEOUT_SECONDS must be between 10 and 180")
        mattermost_webhook_url = os.getenv("MATTERMOST_WEBHOOK_URL") or None
        cookie_secure = os.getenv("COWORK_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}
        if environment == "production" and not mattermost_webhook_url:
            raise RuntimeError("MATTERMOST_WEBHOOK_URL is required in production")
        if environment == "production" and not cookie_secure:
            raise RuntimeError("secure cookies are required in production")
        return cls(
            project_key=project_key,
            jira_base_url=os.getenv("JIRA_BASE_URL", "https://ssafy.atlassian.net").rstrip("/"),
            database_path=Path(os.getenv("COWORK_DATABASE_PATH", ".data/cowork.db")).resolve(),
            cookie_secure=cookie_secure,
            agent_timeout_seconds=timeout,
            mattermost_webhook_url=mattermost_webhook_url,
            hermes_command=os.getenv("HERMES_COMMAND", "hermes"),
            hermes_python=os.getenv(
                "HERMES_PYTHON", "/usr/local/lib/hermes-agent/venv/bin/python"
            ),
        )
