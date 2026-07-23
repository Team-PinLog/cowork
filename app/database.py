from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    jira_account_id TEXT NOT NULL CHECK (length(jira_account_id) > 0),
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    sprint_id INTEGER,
    sprint_name TEXT,
    state TEXT NOT NULL CHECK (state IN ('received','organizing','creating','completed','partial','failed','reconcile')),
    public_message TEXT,
    excluded_json TEXT NOT NULL DEFAULT '[]',
    planned_tasks_json TEXT NOT NULL DEFAULT '[]',
    internal_error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(user_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    issue_key TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_outbox (
    id INTEGER PRIMARY KEY,
    error_text TEXT NOT NULL,
    raw_input TEXT NOT NULL,
    user_name TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_submissions_user ON submissions(user_id, created_at);
"""


class IdempotencyConflict(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = path

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise RuntimeError("database file must be a regular mode-0600 file")
        else:
            os.close(fd)

    def connect(self) -> sqlite3.Connection:
        self._prepare()
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(submissions)")}
            if "planned_tasks_json" not in columns:
                conn.execute(
                    "ALTER TABLE submissions ADD COLUMN planned_tasks_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "sprint_id" not in columns:
                conn.execute("ALTER TABLE submissions ADD COLUMN sprint_id INTEGER")
            if "sprint_name" not in columns:
                conn.execute("ALTER TABLE submissions ADD COLUMN sprint_name TEXT")

    def upsert_user(self, email: str, password_hash: str, display_name: str, jira_account_id: str) -> None:
        if not jira_account_id.strip():
            raise ValueError("jira_account_id is required")
        now = int(time.time())
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO users(email,password_hash,display_name,jira_account_id,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(email) DO UPDATE SET
                     password_hash=excluded.password_hash,
                     display_name=excluded.display_name,
                     jira_account_id=excluded.jira_account_id""",
                (email.strip().lower(), password_hash, display_name.strip(), jira_account_id.strip(), now),
            )
            conn.commit()

    def find_user(self, email: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def create_session(self, token_hash: str, user_id: int, csrf_token: str, expires_at: int) -> None:
        now = int(time.time())
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            conn.execute(
                "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                (token_hash, user_id, csrf_token, expires_at, now),
            )

    def get_session_user(self, token_hash: str) -> tuple[dict[str, Any], str] | None:
        now = int(time.time())
        with self.connect() as conn:
            row = conn.execute(
                """SELECT u.*, s.csrf_token FROM sessions s
                   JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=? AND s.expires_at>?""",
                (token_hash, now),
            ).fetchone()
        return (dict(row), row["csrf_token"]) if row else None

    def delete_session(self, token_hash: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def create_submission(
        self,
        submission_id: str,
        user_id: int,
        idempotency_key: str,
        raw_input: str,
        sprint_id: int,
        sprint_name: str,
    ) -> tuple[str, bool]:
        now = int(time.time())
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT id,raw_input,sprint_id FROM submissions
                   WHERE user_id=? AND idempotency_key=?""",
                (user_id, idempotency_key),
            ).fetchone()
            if row:
                if row["raw_input"] != raw_input or row["sprint_id"] != sprint_id:
                    conn.rollback()
                    raise IdempotencyConflict("idempotency key was reused with different input")
                conn.commit()
                return str(row["id"]), False
            conn.execute(
                """INSERT INTO submissions
                   (id,user_id,idempotency_key,raw_input,sprint_id,sprint_name,state,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    submission_id,
                    user_id,
                    idempotency_key,
                    raw_input,
                    sprint_id,
                    sprint_name,
                    "received",
                    now,
                    now,
                ),
            )
            conn.commit()
        return submission_id, True

    def update_submission(
        self,
        submission_id: str,
        state: str,
        *,
        public_message: str | None = None,
        excluded: list[str] | None = None,
        internal_error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE submissions SET state=?, public_message=?, excluded_json=?,
                   internal_error=?, updated_at=? WHERE id=?""",
                (
                    state,
                    public_message,
                    json.dumps(excluded or [], ensure_ascii=False),
                    internal_error,
                    int(time.time()),
                    submission_id,
                ),
            )

    def save_plan(
        self,
        submission_id: str,
        tasks: list[dict[str, Any]],
        excluded: list[str],
    ) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE submissions
                   SET state='organizing', planned_tasks_json=?, excluded_json=?, updated_at=?
                   WHERE id=? AND state='organizing'""",
                (
                    json.dumps(tasks, ensure_ascii=False),
                    json.dumps(excluded, ensure_ascii=False),
                    int(time.time()),
                    submission_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("submission plan was not persisted")

    def claim_confirmation(self, submission_id: str, user_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE submissions SET state='creating', updated_at=?
                   WHERE id=? AND user_id=? AND state='organizing'
                     AND planned_tasks_json != '[]'""",
                (int(time.time()), submission_id, user_id),
            )
        return cursor.rowcount == 1

    def add_ticket(self, submission_id: str, issue_key: str, summary: str, url: str) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO tickets(submission_id,issue_key,summary,url,created_at) VALUES(?,?,?,?,?)",
                (submission_id, issue_key, summary, url, int(time.time())),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("ticket receipt was not persisted")

    def enqueue_alert(self, *, error: str, raw_input: str, user_name: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO alert_outbox(error_text,raw_input,user_name,created_at)
                   VALUES(?,?,?,?)""",
                (error, raw_input, user_name, int(time.time())),
            )

    def list_pending_alerts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,error_text,raw_input,user_name FROM alert_outbox
                   WHERE delivered_at IS NULL ORDER BY id LIMIT 100"""
            ).fetchall()
        return [dict(row) for row in rows]

    def record_alert_attempt(self, alert_id: int, *, delivered: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE alert_outbox SET attempts=attempts+1,
                   delivered_at=CASE WHEN ? THEN ? ELSE delivered_at END WHERE id=?""",
                (delivered, int(time.time()), alert_id),
            )

    def get_submission(self, submission_id: str, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM submissions WHERE id=? AND user_id=?", (submission_id, user_id)
            ).fetchone()
            if not row:
                return None
            tickets = conn.execute(
                "SELECT issue_key,summary,url FROM tickets WHERE submission_id=? ORDER BY id",
                (submission_id,),
            ).fetchall()
        result = dict(row)
        result["excluded"] = json.loads(result.pop("excluded_json"))
        result["preview"] = json.loads(result.pop("planned_tasks_json"))
        result["tickets"] = [dict(ticket) for ticket in tickets]
        result.pop("raw_input", None)
        result.pop("internal_error", None)
        result.pop("idempotency_key", None)
        return result

    def get_submission_for_worker(self, submission_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT s.*,u.display_name,u.jira_account_id FROM submissions s
                   JOIN users u ON u.id=s.user_id WHERE s.id=?""",
                (submission_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["excluded"] = json.loads(result.pop("excluded_json"))
        result["planned_tasks"] = json.loads(result.pop("planned_tasks_json"))
        return result

    def list_inflight_submissions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT s.id,s.state,s.raw_input,u.display_name FROM submissions s
                   JOIN users u ON u.id=s.user_id
                   WHERE s.state IN ('received','creating')
                      OR (s.state='organizing' AND s.planned_tasks_json='[]')"""
            ).fetchall()
        return [dict(row) for row in rows]
