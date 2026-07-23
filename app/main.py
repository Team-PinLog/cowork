from __future__ import annotations

import secrets
import time
import uuid
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import BackgroundTasks, Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import HermesJiraAgent
from .alerts import MattermostAlerter
from .config import Settings
from .database import Database, IdempotencyConflict
from .roles import ticket_description, ticket_summary, validate_role_tag
from .security import hash_password, new_token, token_digest, verify_password
from .worker import SubmissionWorker

COOKIE_NAME = "cowork_session"
SESSION_SECONDS = 30 * 24 * 60 * 60
DUMMY_PASSWORD_HASH = hash_password("cowork-dummy-password-never-used")


class LoginLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[tuple[int, float]]] = {}
        self._next_reservation = 0
        self._lock = Lock()

    def _keys(self, ip: str, email: str) -> tuple[str, str]:
        email_digest = sha256(email.strip().lower().encode()).hexdigest()
        return f"ip:{ip}", f"email:{email_digest}"

    def reserve(self, ip: str, email: str) -> int | None:
        now = time.monotonic()
        keys = self._keys(ip, email)
        with self._lock:
            for key in keys:
                recent = [
                    attempt
                    for attempt in self._attempts.get(key, [])
                    if now - attempt[1] < self.window_seconds
                ]
                self._attempts[key] = recent
                if len(recent) >= self.max_attempts:
                    return None
            self._next_reservation += 1
            reservation = self._next_reservation
            for key in keys:
                self._attempts[key].append((reservation, now))
            return reservation

    def release_success(self, ip: str, email: str, reservation: int) -> None:
        ip_key, email_key = self._keys(ip, email)
        with self._lock:
            self._attempts[ip_key] = [
                attempt
                for attempt in self._attempts.get(ip_key, [])
                if attempt[0] != reservation
            ]
            self._attempts.pop(email_key, None)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class SubmissionRequest(BaseModel):
    text: str = Field(max_length=10_000)
    idempotency_key: str = Field(min_length=36, max_length=36)
    sprint_id: int = Field(gt=0)


class DraftTaskRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class DraftUpdateRequest(BaseModel):
    tasks: list[DraftTaskRequest] = Field(min_length=1, max_length=20)


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    worker: SubmissionWorker | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    database = database or Database(settings.database_path)
    database.initialize()
    worker = worker or SubmissionWorker(
        database,
        HermesJiraAgent(settings),
        MattermostAlerter(settings.mattermost_webhook_url),
    )
    login_limiter = LoginLimiter()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        recover = getattr(worker, "recover_inflight", None)
        if callable(recover):
            recover()
        yield

    app = FastAPI(
        title="할 일 올리기",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.worker = worker
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    def session_context(session_token: str | None) -> tuple[dict[str, Any], str, str]:
        if not session_token:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다")
        digest = token_digest(session_token)
        found = database.get_session_user(digest)
        if not found:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다")
        user, csrf_token = found
        return user, csrf_token, digest

    def require_csrf(expected: str, provided: str | None) -> None:
        if not provided or not secrets.compare_digest(expected, provided):
            raise HTTPException(status_code=403, detail="요청을 확인할 수 없습니다")

    def active_sprints() -> list[Any]:
        try:
            return worker.list_active_sprints()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="활성 스프린트를 불러오지 못했어요. 잠시 후 다시 시도해주세요",
            ) from exc

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/me")
    def me(cowork_session: str | None = Cookie(default=None)) -> dict[str, Any]:
        if not cowork_session:
            return {"authenticated": False}
        found = database.get_session_user(token_digest(cowork_session))
        if not found:
            return {"authenticated": False}
        user, csrf_token = found
        return {
            "authenticated": True,
            "display_name": user["display_name"],
            "csrf_token": csrf_token,
        }

    @app.post("/api/login")
    def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        client_ip = request.client.host if request.client else "unknown"
        reservation = login_limiter.reserve(client_ip, payload.email)
        if reservation is None:
            raise HTTPException(
                status_code=429,
                detail="로그인 시도가 많아요. 잠시 후 다시 시도해주세요",
            )
        user = database.find_user(payload.email)
        if not user:
            verify_password(payload.password, DUMMY_PASSWORD_HASH)
            raise HTTPException(
                status_code=404,
                detail="등록되지 않은 계정이에요. 팀 리드에게 요청하세요",
            )
        if not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호를 확인하세요")
        login_limiter.release_success(client_ip, payload.email, reservation)
        session_token = new_token()
        csrf_token = new_token()
        database.create_session(
            token_digest(session_token),
            user["id"],
            csrf_token,
            int(time.time()) + SESSION_SECONDS,
        )
        response.set_cookie(
            COOKIE_NAME,
            session_token,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return {"display_name": user["display_name"]}

    @app.get("/api/sprints")
    def list_active_sprints(
        cowork_session: str | None = Cookie(default=None),
    ) -> dict[str, Any]:
        session_context(cowork_session)
        return {
            "sprints": [
                {"id": sprint.id, "name": sprint.name} for sprint in active_sprints()
            ]
        }

    @app.post("/api/logout", status_code=204)
    def logout(
        cowork_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> Response:
        user, csrf_token, digest = session_context(cowork_session)
        del user
        require_csrf(csrf_token, x_csrf_token)
        database.delete_session(digest)
        result = Response(status_code=204)
        result.delete_cookie(COOKIE_NAME, path="/")
        return result

    @app.post("/api/submissions", status_code=202)
    def submit(
        payload: SubmissionRequest,
        background_tasks: BackgroundTasks,
        cowork_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        user, csrf_token, _ = session_context(cowork_session)
        require_csrf(csrf_token, x_csrf_token)
        raw_input = payload.text
        if not raw_input.strip():
            raise HTTPException(status_code=400, detail="할 일을 입력해주세요")
        try:
            role_tag = validate_role_tag(user.get("role_tag") or "")
        except ValueError:
            raise HTTPException(
                status_code=409,
                detail="역할 태그가 등록되지 않았어요. 팀 리드에게 요청하세요",
            ) from None
        try:
            uuid.UUID(payload.idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="요청을 확인할 수 없습니다") from exc
        selected_sprint = next(
            (sprint for sprint in active_sprints() if sprint.id == payload.sprint_id),
            None,
        )
        if not selected_sprint:
            raise HTTPException(
                status_code=409,
                detail="선택한 스프린트가 더 이상 활성 상태가 아니에요",
            )
        try:
            submission_id, created = database.create_submission(
                str(uuid.uuid4()),
                user["id"],
                payload.idempotency_key,
                raw_input,
                selected_sprint.id,
                selected_sprint.name,
                role_tag,
                user["display_name"],
                user["jira_account_id"],
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail="요청을 다시 확인해주세요") from exc
        if created:
            background_tasks.add_task(worker.prepare, submission_id)
        return {"submission_id": submission_id}

    @app.post("/api/submissions/{submission_id}/confirm", status_code=202)
    def confirm_submission(
        submission_id: str,
        background_tasks: BackgroundTasks,
        cowork_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        user, csrf_token, _ = session_context(cowork_session)
        require_csrf(csrf_token, x_csrf_token)
        try:
            uuid.UUID(submission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다") from exc
        submission = database.get_submission(submission_id, user["id"])
        if not submission:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다")
        preview = submission["preview"]
        if not preview:
            raise HTTPException(status_code=409, detail="티켓 정보를 다시 확인해주세요")
        if any(
            ticket_description(task.get("description")) is None
            for task in preview
        ):
            raise HTTPException(status_code=409, detail="모든 티켓의 설명을 입력해주세요")
        if submission["state"] == "organizing" and not any(
            sprint.id == submission["sprint_id"] for sprint in active_sprints()
        ):
            raise HTTPException(
                status_code=409,
                detail="선택한 스프린트가 더 이상 활성 상태가 아니에요",
            )
        claimed = database.claim_confirmation(submission_id, user["id"])
        if claimed:
            background_tasks.add_task(worker.create, submission_id)
        elif submission["state"] not in {"creating", "completed", "partial", "reconcile"}:
            raise HTTPException(status_code=409, detail="티켓 정보를 다시 확인해주세요")
        return {"submission_id": submission_id}

    @app.put("/api/submissions/{submission_id}/draft")
    def update_submission_draft(
        submission_id: str,
        payload: DraftUpdateRequest,
        cowork_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        user, csrf_token, _ = session_context(cowork_session)
        require_csrf(csrf_token, x_csrf_token)
        try:
            uuid.UUID(submission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다") from exc
        submission = database.get_submission(submission_id, user["id"])
        if not submission:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다")
        if submission["state"] != "organizing" or not submission["preview"]:
            raise HTTPException(status_code=409, detail="더 이상 수정할 수 없는 티켓입니다")
        try:
            tasks = []
            for task in payload.tasks:
                description = ticket_description(task.description)
                if description is None:
                    raise HTTPException(status_code=422, detail="티켓 설명을 입력해주세요")
                tasks.append(
                    {
                        "summary": ticket_summary(task.summary, submission["role_tag"]),
                        "description": description,
                    }
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="티켓 제목을 확인해주세요") from exc
        if not database.update_planned_tasks(submission_id, user["id"], tasks):
            raise HTTPException(status_code=409, detail="더 이상 수정할 수 없는 티켓입니다")
        return {"preview": tasks}

    @app.get("/api/submissions/{submission_id}")
    def submission_status(
        submission_id: str,
        cowork_session: str | None = Cookie(default=None),
    ) -> dict[str, Any]:
        user, _, _ = session_context(cowork_session)
        try:
            uuid.UUID(submission_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다") from exc
        submission = database.get_submission(submission_id, user["id"])
        if not submission:
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다")
        state = (
            "review"
            if submission["state"] == "organizing" and submission["preview"]
            else submission["state"]
        )
        progress = {
            "received": "할 일 정리하는 중",
            "organizing": "할 일 정리하는 중",
            "creating": "티켓 만드는 중",
        }.get(state)
        return {
            "state": state,
            "progress": progress,
            "message": submission["public_message"],
            "sprint": {
                "id": submission["sprint_id"],
                "name": submission["sprint_name"],
            },
            "assignee": {
                "display_name": submission["assignee_display_name"],
                "role_tag": submission["role_tag"],
            },
            "preview": submission["preview"],
            "tickets": submission["tickets"],
            "retryable": state == "failed",
        }

    return app
