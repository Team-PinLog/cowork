# 할 일 올리기

팀원이 자연어로 할 일만 적으면 서버 agent가 Jira MCP를 통해 `S15P11A705` 프로젝트에 Task를 생성하는 단일 목적 프로토타입입니다.

## 범위

- 사전 등록 이메일/비밀번호 로그인
- 30일 세션
- 자연어 입력 한 개
- 로그인 사용자의 Jira accountId로 자동 담당자 지정
- 생성 진행 상태와 이번 브라우저 세션의 티켓 영수증
- 원문 선저장, idempotency, 부분 실패, Mattermost 실패 알림

조회·검색·수정·삭제·프로젝트 선택·타입 선택·스프린트·계층·관리 화면은 만들지 않습니다.

## 구조

- FastAPI + vanilla HTML/CSS/JS
- private SQLite: 사용자, 세션, 생성 요청 원문, 생성 결과
- Hermes planner: 자연어를 평평한 Task 목록으로 정리
- direct Atlassian MCP bridge: 허용된 `createJiraIssue` 하나만 호출
- Mattermost Incoming Webhook: Jira/agent 실패 원문과 입력 원문을 리드에게 전달

화면은 서버의 과거 생성 내역을 조회하지 않습니다. SQLite 기록은 입력 유실 방지와 장애 조사만을 위한 내부 데이터입니다.

## 설치

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
cp .env.example .env
chmod 600 .env
```

`.env`에서 실제 `MATTERMOST_WEBHOOK_URL`을 설정합니다. production에서는 Mattermost webhook URL과 secure cookie가 없으면 앱이 시작되지 않습니다. Jira 인증은 `cowork` 전용 OS 계정의 `atlassian` Hermes MCP OAuth를 사용합니다. root의 Hermes profile을 서비스에 노출하지 않습니다.

## 사용자 등록

비밀번호와 Jira accountId는 repository나 shell argument에 넣지 않습니다. Jira accountId는 표시 이름으로 MCP에서 정확히 조회하고, 비밀번호는 TTY에서 두 번 입력합니다.

```bash
set -a; . ./.env; set +a
.venv/bin/python -m app.seed_user \
  --email 'member@example.com' \
  --display-name '홍길동'
```

`jira_account_id` 조회가 유일하지 않거나 누락되면 등록이 거부됩니다.

## 로컬 실행

```bash
set -a; . ./.env; set +a
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8080
```

TLS reverse proxy 뒤에서 운영합니다. `COWORK_COOKIE_SECURE=true`를 유지합니다.

## 컨테이너와 k3s 배포

`Dockerfile`은 Python과 Hermes Agent 버전을 고정하고 UID/GID 1000의 non-root
사용자로 실행합니다. SQLite와 Hermes profile/OAuth 상태는 `/data` 아래에 두며,
운영에서는 하나의 영속 PVC를 마운트합니다. image tag는 Git commit SHA만 사용하고
`main` CI가 검증한 image만 GHCR에 게시합니다.

실제 배포는 PinLog k3s와 Argo CD GitOps로 관리합니다. SQLite singleton이므로
replica는 1이고 Deployment 전략은 `Recreate`여야 합니다. Tunnel token, Mattermost
webhook, provider/OAuth credential은 image나 이 저장소에 포함하지 않습니다.

요청 key는 불명확한 network 실패 동안 browser sessionStorage에 유지됩니다. Jira 생성 후 local receipt 저장 여부가 불명확하면 자동 재시도하지 않고 내부 `reconcile` 상태로 남기며 리드 알림을 보냅니다. Mattermost 전송 실패는 private SQLite outbox에 보존됩니다.

## 검증

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/python -m compileall -q app tests
```

테스트는 Jira와 Mattermost를 mock하며 실제 티켓을 생성하지 않습니다.
