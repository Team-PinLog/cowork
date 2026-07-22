from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

MATTERMOST_MESSAGE_LIMIT = 3_000
TRUNCATION_MARKER = "…[잘림]"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:limit]
    return value[: limit - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


class MattermostAlerter:
    def __init__(self, webhook_url: str | None):
        self.webhook_url = webhook_url

    def send_failure(self, *, error: str, raw_input: str, user_name: str) -> None:
        if not self.webhook_url:
            raise RuntimeError("MATTERMOST_WEBHOOK_URL is not configured")
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        user = _truncate(user_name, 100)
        header = (
            "[할 일 올리기] 티켓 생성 실패\n"
            f"사용자: {user}\n"
            f"시각: {timestamp}\n"
        )
        labels = "입력 원문:\n" + "\n오류 원문:\n"
        available = MATTERMOST_MESSAGE_LIMIT - len(header) - len(labels)
        minimum_error_budget = min(600, available // 2)
        input_text = _truncate(raw_input, available - minimum_error_budget)
        error_text = _truncate(error, available - len(input_text))
        text = (
            f"{header}"
            f"입력 원문:\n{input_text}\n"
            f"오류 원문:\n{error_text}"
        ).replace("@", "＠")
        payload = {"text": text}
        request = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                raise RuntimeError("Mattermost alert delivery failed")
