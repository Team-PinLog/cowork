from __future__ import annotations

import json
import re
import sys
from typing import Any, NoReturn

from tools.mcp_tool import discover_mcp_tools
from tools.registry import registry

TOOL_NAME = "mcp__atlassian__createJiraIssue"
ALLOWED = {
    "cloudId",
    "projectKey",
    "issueTypeName",
    "summary",
    "description",
    "assignee_account_id",
    "contentFormat",
    "additional_fields",
}


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _ambiguous() -> NoReturn:
    json.dump({"error": "post_create_ambiguous"}, sys.stdout)
    raise SystemExit(42)


def main() -> None:
    try:
        payload: Any = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SystemExit("invalid request")
    if not isinstance(payload, dict) or set(payload) - ALLOWED:
        raise SystemExit("invalid request")
    required = {"cloudId", "projectKey", "issueTypeName", "summary", "assignee_account_id"}
    if not required.issubset(payload):
        raise SystemExit("invalid request")
    if payload["issueTypeName"] != "Task":
        raise SystemExit("invalid request")
    if not all(isinstance(payload[key], str) and payload[key] for key in required):
        raise SystemExit("invalid request")
    additional_fields = payload.get("additional_fields")
    if (
        not isinstance(additional_fields, dict)
        or set(additional_fields) != {"customfield_10020"}
        or not isinstance(additional_fields["customfield_10020"], int)
        or isinstance(additional_fields["customfield_10020"], bool)
        or additional_fields["customfield_10020"] <= 0
    ):
        raise SystemExit("invalid request")

    discover_mcp_tools()
    try:
        raw = registry.dispatch(TOOL_NAME, payload)
    except Exception:
        _ambiguous()
    try:
        outer = _decode(raw)
        if not isinstance(outer, dict) or set(outer) != {"result"}:
            _ambiguous()
        body = _decode(outer["result"])
        if not isinstance(body, dict):
            _ambiguous()
        if set(body) == {"statusCode", "data"}:
            if body["statusCode"] not in {200, 201}:
                raise SystemExit("create failed")
            data = body["data"]
        elif set(body) == {"id", "key", "self"}:
            data = body
        else:
            _ambiguous()
        if not isinstance(data, dict) or not set(data).issubset({"id", "key", "self"}):
            _ambiguous()
        issue_key = data.get("key")
        if not isinstance(issue_key, str) or not re.fullmatch(
            rf"{re.escape(payload['projectKey'])}-\d+", issue_key
        ):
            _ambiguous()
    except (KeyError, TypeError, json.JSONDecodeError):
        _ambiguous()
    json.dump({"issue_key": issue_key}, sys.stdout)


if __name__ == "__main__":
    main()
