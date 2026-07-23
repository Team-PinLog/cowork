import importlib
import io
import json
import sys
import types
from types import SimpleNamespace

import pytest


def test_dispatch_exception_exits_as_post_create_ambiguous(monkeypatch, capsys):
    tools_package = types.ModuleType("tools")
    mcp_module = types.ModuleType("tools.mcp_tool")
    registry_module = types.ModuleType("tools.registry")

    mcp_module.discover_mcp_tools = lambda: None

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("synthetic MCP timeout")

    registry_module.registry = SimpleNamespace(dispatch=raise_timeout)
    monkeypatch.setitem(sys.modules, "tools", tools_package)
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", mcp_module)
    monkeypatch.setitem(sys.modules, "tools.registry", registry_module)
    sys.modules.pop("app.mcp_create_bridge", None)
    bridge = importlib.import_module("app.mcp_create_bridge")

    request = {
        "cloudId": "https://ssafy.atlassian.net",
        "projectKey": "S15P11A705",
        "issueTypeName": "Task",
        "summary": "합성 작업",
        "assignee_account_id": "synthetic-account",
        "contentFormat": "markdown",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))

    with pytest.raises(SystemExit) as exc_info:
        bridge.main()

    assert exc_info.value.code == 42
    assert json.loads(capsys.readouterr().out) == {"error": "post_create_ambiguous"}


def test_direct_atlassian_create_response_returns_issue_key(monkeypatch, capsys):
    tools_package = types.ModuleType("tools")
    mcp_module = types.ModuleType("tools.mcp_tool")
    registry_module = types.ModuleType("tools.registry")

    mcp_module.discover_mcp_tools = lambda: None
    registry_module.registry = SimpleNamespace(
        dispatch=lambda *_args, **_kwargs: {
            "result": json.dumps(
                {
                    "id": "1561640",
                    "key": "S15P11A705-17",
                    "self": "https://api.atlassian.com/ex/jira/site/rest/api/3/issue/1561640",
                }
            )
        }
    )
    monkeypatch.setitem(sys.modules, "tools", tools_package)
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", mcp_module)
    monkeypatch.setitem(sys.modules, "tools.registry", registry_module)
    sys.modules.pop("app.mcp_create_bridge", None)
    bridge = importlib.import_module("app.mcp_create_bridge")

    request = {
        "cloudId": "https://ssafy.atlassian.net",
        "projectKey": "S15P11A705",
        "issueTypeName": "Task",
        "summary": "합성 작업",
        "assignee_account_id": "synthetic-account",
        "contentFormat": "markdown",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))

    bridge.main()

    assert json.loads(capsys.readouterr().out) == {"issue_key": "S15P11A705-17"}
