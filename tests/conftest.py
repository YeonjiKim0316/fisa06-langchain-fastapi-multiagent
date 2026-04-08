"""
공유 pytest 픽스처.
- 인메모리 SQLite (StaticPool) 으로 DB 격리
- 임시 디렉터리로 파일 스토리지 격리
- 인증된 클라이언트 헬퍼 픽스처 제공
"""
import os
import shutil
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── 1. 테스트 환경 변수 설정 (모든 임포트 전) ──────────────────────────────
os.environ["APP_ENV"] = "test"

_ENV_FILE = ".env.test"
with open(_ENV_FILE, "w", encoding="utf-8") as _f:
    _f.write(
        "APP_ENV=test\n"
        "DATABASE_URL=sqlite:///:memory:\n"
        "LOCAL_STORAGE_DIR=test_reports\n"
        # JWT 최소 권장 길이 32바이트 이상 사용 (기존 'testsecret' 10바이트 경고 해결)
        "SECRET_KEY=test-secret-key-that-is-at-least-32-bytes-long\n"
    )

# ── 2. settings lru_cache 초기화 ──────────────────────────────────────────
from core.config import get_settings
get_settings.cache_clear()

# ── 3. 모델 임포트 (Base.metadata에 테이블 등록) ──────────────────────────
import models.user    # noqa: F401
import models.report  # noqa: F401

# ── 4. 앱 및 DB 임포트 ────────────────────────────────────────────────────
import core.database
from core.database import Base
from main import app

# ── 5. 테스트용 인메모리 엔진 + SessionLocal 생성 ─────────────────────────
#    StaticPool: 같은 프로세스 내 모든 커넥션이 동일한 인메모리 DB를 공유
_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE)

# core.database 교체 → 모든 함수 내 임포트는 이걸 사용 (auth_service 포함)
core.database.engine = _TEST_ENGINE
core.database.SessionLocal = _TestSessionLocal  # type: ignore[assignment]

# ── 6. 세션 직렬화기를 테스트 시크릿으로 재초기화 ──────────────────────────
from itsdangerous import URLSafeSerializer
import core.session as _session_mod
_session_mod._serializer = URLSafeSerializer(
    get_settings().secret_key, salt="session"
)


# ═══════════════════════════════════════════════
# 세션 범위 픽스처: DB 스키마 생성 / 스토리지 디렉터리
# ═══════════════════════════════════════════════

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """테스트 세션 시작 시 DB 테이블 생성, 종료 시 정리."""
    Base.metadata.create_all(bind=_TEST_ENGINE)
    os.makedirs("test_reports", exist_ok=True)
    yield
    Base.metadata.drop_all(bind=_TEST_ENGINE)
    if os.path.exists(_ENV_FILE):
        os.remove(_ENV_FILE)
    if os.path.exists("test_reports"):
        shutil.rmtree("test_reports")


# ═══════════════════════════════════════════════
# 함수 범위 픽스처: 각 테스트마다 독립 DB 세션
# ═══════════════════════════════════════════════

@pytest.fixture
def db_session():
    """테스트마다 격리된 DB 세션 제공 (종료 시 테이블 데이터 초기화)."""
    session = _TestSessionLocal()
    yield session
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


@pytest.fixture
def client(db_session):
    """FastAPI TestClient — 각 테스트마다 DB가 초기화된 상태로 시작."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ═══════════════════════════════════════════════
# 헬퍼 픽스처: 인증 상태 클라이언트
# ═══════════════════════════════════════════════

@pytest.fixture
def test_user(client):
    """테스트용 유저 생성 후 {'email', 'password', 'token'} 반환."""
    email = "fixture@example.com"
    password = "fixture-password-123"
    resp = client.post(
        "/auth/signup",
        data={"email": email, "password": password, "full_name": "Fixture User"},
        follow_redirects=False,
    )
    assert resp.status_code == 302, f"회원가입 실패 (status={resp.status_code})"
    token = resp.cookies.get("access_token")
    assert token, "access_token 쿠키가 없음"
    return {"email": email, "password": password, "token": token}


@pytest.fixture
def auth_client(client, test_user):
    """access_token 쿠키가 설정된 인증된 TestClient."""
    client.cookies.set("access_token", test_user["token"])
    yield client
    client.cookies.delete("access_token")
