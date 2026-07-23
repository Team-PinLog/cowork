import hashlib
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
        "할 일 입력 가이드",
        "가이드 복사",
        "작업 목록을 입력하거나 AI가 정리한 내용을 붙여넣어 주세요",
        "AI에게 전달할 가이드를 복사했습니다",
        "티켓 만들기",
        "오늘 만든 티켓",
        "할 일 정리하는 중",
        "티켓 만드는 중",
        "만드는 중",
        "티켓 정보 확인",
        "아래 내용으로 Jira 티켓이 만들어집니다",
        "수정하기",
        "수정 완료",
        "티켓 추가",
        "티켓 삭제",
        "티켓은 최소 1개가 필요합니다",
        "티켓은 최대 20개까지 만들 수 있습니다",
        "스프린트 불러오는 중",
        "수정 내용 저장 중",
        "확인하고 만들기",
        "활성 스프린트",
        "활성 스프린트를 선택해주세요",
        "담당자",
        "태그",
    ):
        assert required in full_contract

    assert 'id="preview-section"' in html
    assert 'id="preview-list"' in html
    assert 'id="confirm-button"' in html
    assert 'id="preview-assignee-name"' in html
    assert 'id="preview-role-tag"' in html
    assert 'id="add-ticket-button"' in html
    assert 'id="ai-guide-prompt"' in html
    assert 'id="copy-guide-button"' in html
    assert "/confirm" in script
    assert "/draft" in script
    assert "preview-summary-input" in script
    assert "preview-description-input" in script
    assert "delete-ticket-button" in script
    assert "setProgress" in script
    assert "progress.classList.toggle('loading'" in script
    assert "navigator.clipboard.writeText" in script
    assert "오늘 할 일을 편하게 적어주세요" not in html

    for forbidden in ("이슈", "이슈 타입", "백로그", "에픽", "스토리", "하위 작업", "어사인", "담당자 배정"):
        assert forbidden not in visible_contract


def test_receipts_are_not_persisted_in_browser_storage():
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "JSON.stringify(receipts)" not in script
    assert "const receipts = []" in script
    assert "cowork_pending_request" in script


def test_static_asset_urls_include_current_content_hash():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    for asset in ("app.js", "style.css"):
        content = Path(f"app/static/{asset}").read_bytes()
        version = hashlib.sha256(content).hexdigest()[:12]
        assert f"/static/{asset}?v={version}" in html
