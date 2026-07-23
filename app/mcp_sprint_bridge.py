from __future__ import annotations

import json
import re
import sys
from typing import Any

from tools.mcp_tool import discover_mcp_tools
from tools.registry import registry

TOOL_NAME = "mcp__atlassian__searchJiraIssuesUsingJql"
SPRINT_FIELD = "customfield_10020"


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def main() -> None:
    try:
        payload: Any = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SystemExit("invalid request")
    if not isinstance(payload, dict) or set(payload) != {"cloudId", "projectKey"}:
        raise SystemExit("invalid request")
    cloud_id = payload["cloudId"]
    project_key = payload["projectKey"]
    if not isinstance(cloud_id, str) or not cloud_id.startswith("https://"):
        raise SystemExit("invalid request")
    if not isinstance(project_key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]+", project_key):
        raise SystemExit("invalid request")

    discover_mcp_tools()
    raw = registry.dispatch(
        TOOL_NAME,
        {
            "cloudId": cloud_id,
            "jql": f"project = {project_key} AND sprint in openSprints() ORDER BY updated DESC",
            "maxResults": 100,
            "fields": [SPRINT_FIELD],
            "searchResultMode": "issues",
        },
    )
    try:
        outer = _decode(raw)
        body = _decode(outer["result"])
        issues = body["issues"]
        if not isinstance(issues, list):
            raise ValueError
        sprints: dict[int, str] = {}
        for issue in issues:
            values = issue.get("fields", {}).get(SPRINT_FIELD) or []
            if not isinstance(values, list):
                raise ValueError
            for sprint in values:
                if not isinstance(sprint, dict) or sprint.get("state") != "active":
                    continue
                sprint_id = sprint.get("id")
                name = sprint.get("name")
                if (
                    not isinstance(sprint_id, int)
                    or isinstance(sprint_id, bool)
                    or sprint_id <= 0
                    or not isinstance(name, str)
                    or not name.strip()
                ):
                    raise ValueError
                sprints[sprint_id] = name.strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("invalid Jira sprint response") from exc

    json.dump(
        {"sprints": [{"id": sprint_id, "name": name} for sprint_id, name in sorted(sprints.items())]},
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
