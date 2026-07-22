from pathlib import Path


def test_required_ci_workflow_is_pinned_and_runs_all_gates():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "contents: read" in workflow
    assert "timeout-minutes: 10" in workflow
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in workflow
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
    for command in (
        'python -m pip install ".[test]"',
        "python -m pytest -q",
        "python -m ruff check app tests",
        "python -m compileall -q app tests",
        "python -m pip check",
    ):
        assert command in workflow
