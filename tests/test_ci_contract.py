from pathlib import Path


def test_required_ci_workflow_is_pinned_and_runs_all_gates():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "contents: read" in workflow
    assert "timeout-minutes: 10" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    for command in (
        'python -m pip install ".[test]"',
        "python -m pytest -q",
        "python -m ruff check app tests",
        "python -m compileall -q app tests",
        "python -m pip check",
    ):
        assert command in workflow

    assert "packages: write" in workflow
    container_job = workflow.split("  container:\n", 1)[1].split("  publish:\n", 1)[0]
    assert "packages: write" not in container_job
    assert "contents: read" in container_job

    publish_job = workflow.split("  publish:\n", 1)[1]
    assert "if: github.event_name == 'push'" in publish_job
    assert "packages: write" in publish_job
    assert "docker/login-action@af1e73f918a031802d376d3c8bbc3fe56130a9b0" in workflow
    assert "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c" in workflow
    assert "docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a" in workflow
    assert "ghcr.io/team-pinlog/cowork:${{ github.sha }}" in workflow
    assert "docker run --detach" in workflow
    assert "curl --fail --silent --show-error http://127.0.0.1:18080/health" in workflow
    assert "docker push" in workflow
    assert ":latest" not in workflow
