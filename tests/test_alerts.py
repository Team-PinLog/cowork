import json

from app.alerts import MattermostAlerter


def test_mattermost_failure_payload_disables_mentions(monkeypatch):
    observed = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        observed["payload"] = json.loads(request.data)
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    MattermostAlerter("https://mattermost.invalid/hooks/example").send_failure(
        error="@channel synthetic error",
        raw_input="@here synthetic input",
        user_name="member",
    )

    payload = observed["payload"]
    assert set(payload) == {"text"}
    assert "@channel" not in payload["text"]
    assert "@here" not in payload["text"]
    assert "＠channel" in payload["text"]
    assert "＠here" in payload["text"]
    assert observed["timeout"] == 10


def test_mattermost_failure_payload_never_exceeds_message_limit(monkeypatch):
    observed = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        observed["payload"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    MattermostAlerter("https://mattermost.invalid/hooks/example").send_failure(
        error="오류" * 2_000,
        raw_input="입력" * 5_000,
        user_name="사용자" * 100,
    )

    text = observed["payload"]["text"]
    assert len(text) <= 3_000
    assert "입력 원문:" in text
    assert "오류 원문:" in text
    assert "[잘림]" in text
