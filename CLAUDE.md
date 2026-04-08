# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

Settings are loaded from `.env.{APP_ENV}` (defaults to `.env.local`). Required keys:

```
SECRET_KEY=...           # itsdangerous session signing + JWT
OPENAI_API_KEY=...
TAVILY_API_KEY=...
DATABASE_URL=...         # defaults to sqlite:///./deepresearch.db
APP_ENV=local            # "prod" switches storage to S3
```

Optional S3 keys (only when `APP_ENV=prod`):
```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=...
S3_BUCKET_NAME=...
```

## Architecture Overview

**FastAPI + Jinja2 + Bootstrap5** web app for AI-powered research report generation.

### Request Flow

1. Auth: `POST /auth/login` → JWT signed with `SECRET_KEY` stored in HTTP-only `access_token` cookie (7-day expiry). Session preferences (language, model) stored in a separate signed `session` cookie via `itsdangerous`.

2. Report Generation (`GET /generate/stream`): SSE endpoint using `sse-starlette`. The LangGraph agent runs in a background `asyncio.Task` posting to a `Queue`; the SSE generator reads from the queue. This prevents the LangGraph coroutine from being cancelled by timeouts.

3. Human-in-the-Loop (HITL): The LangGraph graph is compiled with `interrupt_after=["generate_report_plan"]` and a `SqliteSaver` checkpointer (`checkpoints.db`). After planning, a `plan_generated` SSE event fires. The client re-calls `/generate/stream?thread_id=...&excluded=0,2` to resume, optionally filtering out sections by index.

### Layer Map

| Layer | Files | Responsibility |
|---|---|---|
| Config | `core/config.py` | Pydantic `BaseSettings`, env loading |
| DB | `core/database.py`, `models/` | SQLAlchemy + SQLite; `User`, `Report` models |
| Auth | `services/auth_service.py`, `core/dependencies.py` | bcrypt passwords, PyJWT tokens, `require_user` Depends |
| Session | `core/session.py` | `itsdangerous` signed cookie for per-user preferences |
| Storage | `services/storage_service.py` | `LocalDiskStorage` (default) or `S3Storage` (`APP_ENV=prod`) |
| AI Core | `deep_ai/agent.py`, `deep_ai/prompts.py`, `deep_ai/util.py` | LangGraph state machine, OpenAI + Tavily |
| Routers | `routers/` | HTTP handlers; thin layer calling services |
| Templates | `templates/` | Jinja2 + Bootstrap5 dark glassmorphism theme |

### AI Agent Graph (`deep_ai/agent.py`)

LangGraph `StateGraph` with two sub-graphs:
- **Outer graph** (`reporter_agent`): `generate_report_plan` → (parallel) `section_builder_with_web_search` → `format_completed_sections` → (parallel) `write_final_sections` → `compile_final_report`
- **Inner graph** (`section_builder_subagent`): `generate_queries` → `search_web` → `write_section`

Model name mapping: `"gpt-5"` → `gpt-4o`, `"gpt-5-nano"` → `gpt-4o-mini`.

### Flash Messages

`core/utils.flash()` writes a short-lived (10s) non-httponly cookie named `flash` containing `[[category, message]]`. JavaScript in `base.html` reads and clears it.

### Storage

Reports are saved as `.md` files with a `.json` sidecar (research logs). Path pattern: `{user_id}/{topic}_{timestamp}.md`. Metadata is also stored in the `reports` SQLite table for fast listing.

---

## Testing

```bash
# 빠른 테스트 (API 키 불필요, ~15초)
python -m pytest -m "not slow"

# AI 통합 테스트 (OPENAI_API_KEY + TAVILY_API_KEY 필요)
python -m pytest -m slow
```

### Test Structure

| File | Coverage |
|---|---|
| `tests/test_auth.py` | sign_up/in, JWT 위조·만료, auth 라우터 전체 흐름 |
| `tests/test_storage.py` | LocalDiskStorage CRUD, save/load/delete, 유저 격리 |
| `tests/test_pdf.py` | PDF 바이트 검증, 한글/테이블/코드블록, 다운로드 라우터 |
| `tests/test_routers.py` | 전체 HTTP 엔드포인트 (대시보드, 보고서 CRUD, SSE mock) |
| `tests/test_utils.py` | flash, topic_from_filename, session 왕복 |
| `tests/test_agent.py` | 그래프 노드 구조, 모델 매핑, 병렬화 로직, HITL (slow) |

### Key Fixture Design (`tests/conftest.py`)

- `_TEST_ENGINE`: `StaticPool` SQLite in-memory — 모든 커넥션이 같은 DB 공유
- `db_session`: 각 테스트 후 `table.delete()`로 데이터 초기화 (스키마 유지)
- `auth_client`: `access_token` 쿠키가 설정된 인증된 TestClient

---

## Known Design Notes

- **API 키 흐름**: `POST /settings/apikeys` → 세션 쿠키에만 저장 → `GET /generate/stream`에서 세션 키 우선 읽어 `os.environ`에 주입 (LangGraph 에이전트가 os.environ 직접 참조). 멀티유저 동시 실행 시 키 충돌 가능 — 운영 환경에서는 per-request 주입 구조로 개선 필요.
- **HITL 체크포인트**: `checkpoints.db` (SQLite)가 프로젝트 루트에 생성됨. `deep_ai/agent.py`가 모듈 임포트 시 파일을 열므로 앱 시작이 느릴 수 있음.
- **PDF 폰트**: Windows 전용 `malgun.ttf` 우선 시도, 없으면 `Roboto` → `Helvetica` 폴백.
