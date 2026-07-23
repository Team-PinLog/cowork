from __future__ import annotations

import argparse
import getpass
import json
import re
import subprocess


from .config import Settings
from .database import Database
from .roles import VALID_ROLE_TAGS, role_tag_for
from .security import hash_password


def lookup_account_id(settings: Settings, display_name: str) -> str:
    command = [
        settings.hermes_python,
        "-m",
        "app.mcp_lookup_bridge",
    ]
    result = subprocess.run(
        command,
        input=json.dumps(
            {"cloudId": settings.jira_base_url, "displayName": display_name},
            ensure_ascii=False,
        ),
        capture_output=True,
        text=True,
        timeout=settings.agent_timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Jira account lookup failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Jira account lookup returned an invalid response") from exc
    if set(payload) != {"account_id"}:
        raise RuntimeError("Jira account lookup was not unique")
    account_id = payload["account_id"]
    if not isinstance(account_id, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{8,200}", account_id):
        raise RuntimeError("Jira account lookup returned an invalid identifier")
    return account_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactively seed one cowork user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role-tag", choices=sorted(VALID_ROLE_TAGS))
    args = parser.parse_args()
    role_tag = args.role_tag or role_tag_for(args.display_name)
    if not role_tag:
        raise SystemExit("신규 사용자는 --role-tag가 필요합니다")
    password = getpass.getpass("새 비밀번호: ")
    confirmation = getpass.getpass("새 비밀번호 확인: ")
    if password != confirmation:
        raise SystemExit("비밀번호가 일치하지 않습니다")
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.initialize()
    account_id = lookup_account_id(settings, args.display_name)
    database.upsert_user(
        args.email, hash_password(password), args.display_name, account_id, role_tag
    )
    print(f"등록 완료: {args.display_name}")


if __name__ == "__main__":
    main()
