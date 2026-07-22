from pathlib import Path


def test_screen_contract_and_forbidden_vocabulary():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    backend = Path("app/main.py").read_text(encoding="utf-8")
    visible_contract = html + script
    full_contract = visible_contract + backend

    for required in (
        "할 일 올리기",
        "적어두면 Jira 티켓으로 만들어드려요",
        "name@company.com",
        "오늘 할 일을 편하게 적어주세요",
        "티켓 만들기",
        "오늘 만든 티켓",
        "할 일 정리하는 중",
        "티켓 만드는 중",
        "만드는 중",
    ):
        assert required in full_contract

    for forbidden in ("이슈", "이슈 타입", "백로그", "에픽", "스토리", "하위 작업", "어사인", "담당자 배정", "스프린트"):
        assert forbidden not in visible_contract


def test_receipts_are_not_persisted_in_browser_storage():
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "JSON.stringify(receipts)" not in script
    assert "const receipts = []" in script
    assert "cowork_pending_request" in script
