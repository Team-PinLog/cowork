from pathlib import Path


BASE_IMAGE = (
    "python:3.11.15-slim@"
    "sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
)


def test_container_is_pinned_non_root_and_uses_persistent_paths():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert f"FROM {BASE_IMAGE}" in dockerfile
    assert "hermes-agent==0.19.0" in dockerfile
    assert "USER 1000:1000" in dockerfile
    assert "HERMES_HOME=/data/hermes" in dockerfile
    assert "COWORK_DATABASE_PATH=/data/cowork.db" in dockerfile
    assert "HERMES_PYTHON=/usr/local/bin/python" in dockerfile
    assert 'CMD ["uvicorn", "app.main:create_app", "--factory"' in dockerfile
    assert ":latest" not in dockerfile


def test_container_context_excludes_credentials_and_runtime_data():
    ignored = set(Path(".dockerignore").read_text(encoding="utf-8").splitlines())

    assert {".env", ".data", "*.db", ".git", ".venv"} <= ignored


def test_deployment_contract_targets_kubernetes_not_systemd():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert not Path("deploy/cowork.service").exists()
    assert "k3s" in readme
    assert "systemd" not in readme
