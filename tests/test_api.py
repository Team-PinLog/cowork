from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.security import hash_password


class ImmediateSuccessWorker:
    def __init__(self, database: Database):
        self.database = database
        self.prepare_calls = 0
        self.create_calls = 0

    def prepare(self, submission_id: str) -> None:
        self.prepare_calls += 1
        self.database.update_submission(submission_id, "organizing")
        self.database.save_plan(
            submission_id,
            [{"summary": "결제 연동 완료", "description": None}],
            [],
        )

    def create(self, submission_id: str) -> None:
        self.create_calls += 1
        submission = self.database.get_submission_for_worker(submission_id)
        self.database.add_ticket(
            submission_id,
            "S15P11A705-101",
            "결제 연동 완료",
            "https://ssafy.atlassian.net/browse/S15P11A705-101",
        )
        self.database.update_submission(submission_id, "completed")
        assert submission["raw_input"] == "카카오페이 연동 마저 하기"

    def process(self, submission_id: str) -> None:
        self.create(submission_id)


@pytest.fixture
def client_and_worker(tmp_path):
    settings = Settings(
        project_key="S15P11A705",
        jira_base_url="https://ssafy.atlassian.net",
        database_path=tmp_path / "cowork.db",
        cookie_secure=False,
        agent_timeout_seconds=60,
        mattermost_webhook_url=None,
        hermes_command="hermes",
    )
    database = Database(settings.database_path)
    database.initialize()
    database.upsert_user(
        "member@example.com", hash_password("safe-password-123"), "김팀원", "jira-account-1"
    )
    worker = ImmediateSuccessWorker(database)
    with TestClient(create_app(settings, database=database, worker=worker)) as client:
        yield client, worker, database


def login(client: TestClient):
    response = client.post(
        "/api/login",
        json={"email": "member@example.com", "password": "safe-password-123"},
    )
    assert response.status_code == 200
    me = client.get("/api/me").json()
    return me["csrf_token"]


def test_login_messages_and_30_day_session(client_and_worker):
    client, _, _ = client_and_worker
    unknown = client.post("/api/login", json={"email": "none@example.com", "password": "x"})
    assert unknown.json()["detail"] == "등록되지 않은 계정이에요. 팀 리드에게 요청하세요"

    wrong = client.post(
        "/api/login", json={"email": "member@example.com", "password": "wrong"}
    )
    assert wrong.json()["detail"] == "이메일 또는 비밀번호를 확인하세요"

    ok = client.post(
        "/api/login",
        json={"email": "member@example.com", "password": "safe-password-123"},
    )
    assert ok.status_code == 200
    assert "Max-Age=2592000" in ok.headers["set-cookie"]
    assert client.get("/api/me").json()["display_name"] == "김팀원"


def test_submission_requires_preview_confirmation_before_ticket_creation(client_and_worker):
    client, worker, _ = client_and_worker
    csrf = login(client)
    key = str(uuid.uuid4())
    payload = {"text": "카카오페이 연동 마저 하기", "idempotency_key": key}
    first = client.post("/api/submissions", json=payload, headers={"X-CSRF-Token": csrf})
    second = client.post("/api/submissions", json=payload, headers={"X-CSRF-Token": csrf})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["submission_id"] == second.json()["submission_id"]
    assert worker.prepare_calls == 1
    assert worker.create_calls == 0
    mismatch = client.post(
        "/api/submissions",
        json={"text": "다른 작업", "idempotency_key": key},
        headers={"X-CSRF-Token": csrf},
    )
    assert mismatch.status_code == 409

    submission_id = first.json()["submission_id"]
    preview = client.get(f"/api/submissions/{submission_id}").json()
    assert preview["state"] == "review"
    assert preview["preview"] == [
        {"summary": "결제 연동 완료", "description": None}
    ]
    assert preview["tickets"] == []

    confirmed = client.post(
        f"/api/submissions/{submission_id}/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 202
    assert worker.create_calls == 1

    status = client.get(f"/api/submissions/{submission_id}").json()
    assert status["state"] == "completed"
    assert status["tickets"] == [
        {
            "issue_key": "S15P11A705-101",
            "summary": "결제 연동 완료",
            "url": "https://ssafy.atlassian.net/browse/S15P11A705-101",
        }
    ]


def test_csrf_and_cross_user_submission_access_are_blocked(client_and_worker):
    client, _, database = client_and_worker
    csrf = login(client)
    denied = client.post(
        "/api/submissions",
        json={"text": "작업", "idempotency_key": str(uuid.uuid4())},
    )
    assert denied.status_code == 403

    response = client.post(
        "/api/submissions",
        json={"text": "카카오페이 연동 마저 하기", "idempotency_key": str(uuid.uuid4())},
        headers={"X-CSRF-Token": csrf},
    )
    submission_id = response.json()["submission_id"]
    database.upsert_user(
        "other@example.com", hash_password("another-safe-password"), "다른 사용자", "jira-account-2"
    )
    client.cookies.clear()
    client.post(
        "/api/login", json={"email": "other@example.com", "password": "another-safe-password"}
    )
    assert client.get(f"/api/submissions/{submission_id}").status_code == 404


def test_logout_returns_real_204_and_clears_session(client_and_worker):
    client, _, _ = client_and_worker
    csrf = login(client)
    response = client.post("/api/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    assert client.get("/api/me").json() == {"authenticated": False}


def test_login_is_throttled_after_repeated_failures(client_and_worker):
    client, _, _ = client_and_worker
    for _ in range(5):
        response = client.post(
            "/api/login", json={"email": "member@example.com", "password": "wrong"}
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/login", json={"email": "member@example.com", "password": "wrong"}
    )
    assert blocked.status_code == 429
