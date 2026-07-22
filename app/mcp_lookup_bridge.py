from __future__ import annotations

import json
import sys
from typing import Any

from tools.mcp_tool import discover_mcp_tools
from tools.registry import registry

TOOL_NAME = "mcp__atlassian__lookupJiraAccountId"


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def main() -> None:
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SystemExit("invalid request")
    if not isinstance(request, dict) or set(request) != {"cloudId", "displayName"}:
        raise SystemExit("invalid request")
    if not all(isinstance(value, str) and value for value in request.values()):
        raise SystemExit("invalid request")

    discover_mcp_tools()
    raw = registry.dispatch(
        TOOL_NAME,
        {"cloudId": request["cloudId"], "searchString": request["displayName"]},
    )
    try:
        outer = _decode(raw)
        body = _decode(outer["result"])
        users_block = body["data"]["users"]
        users = users_block["users"]
    except (KeyError, TypeError, json.JSONDecodeError):
        raise SystemExit("lookup failed")
    exact = [
        user
        for user in users
        if isinstance(user, dict) and user.get("displayName") == request["displayName"]
    ]
    if users_block.get("total") != 1 or len(exact) != 1:
        raise SystemExit("lookup was not unique")
    account_id = exact[0].get("accountId")
    if not isinstance(account_id, str) or not account_id:
        raise SystemExit("lookup returned no account identifier")
    json.dump({"account_id": account_id}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
