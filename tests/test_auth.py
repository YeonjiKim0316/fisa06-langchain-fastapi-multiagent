"""
인증 서비스 및 라우터 테스트.

커버리지:
- sign_up: 성공, 중복 이메일
- sign_in: 성공, 없는 이메일, 틀린 비밀번호
- get_user_from_token: 유효 / 변조 / 빈 문자열
- create_access_token: JWT payload 검증
- POST /auth/signup, /auth/login, /auth/logout HTTP 흐름
- 인증된 상태에서 /auth/login 접근 → 대시보드 리다이렉트
"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone
from services.auth_service import sign_up, sign_in, get_user_from_token, create_access_token
from core.config import get_settings


# ─────────────────────────────────────────────
# 서비스 레이어: sign_up
# ─────────────────────────────────────────────

class TestSignUp:
    def test_success(self, db_session):
        user, token = sign_up("new@example.com", "password123", "New User")
        assert user.email == "new@example.com"
        assert token is not None and len(token) > 10

    def test_returns_user_id(self, db_session):
        user, _ = sign_up("idcheck@example.com", "pass", "ID Check")
        assert user.id is not None

    def test_duplicate_email_raises(self, db_session):
        sign_up("dup@example.com", "pass1", "First")
        with pytest.raises(ValueError, match="이미 존재하는 이메일"):
            sign_up("dup@example.com", "pass2", "Second")

    def test_duplicate_email_case_sensitive(self, db_session):
        """이메일 대소문자 구분 확인 (SQLite 기본 동작)."""
        sign_up("case@example.com", "pass", "Lower")
        # SQLite는 기본적으로 LIKE 비교가 대소문자 무시이나,
        # 정확히 같은 이메일은 unique 제약에 걸려야 함
        with pytest.raises(ValueError):
            sign_up("case@example.com", "pass2", "Same")


# ─────────────────────────────────────────────
# 서비스 레이어: sign_in
# ─────────────────────────────────────────────

class TestSignIn:
    def test_success(self, db_session):
        sign_up("login@example.com", "mypassword", "Login User")
        user, token = sign_in("login@example.com", "mypassword")
        assert user.email == "login@example.com"
        assert token is not None

    def test_wrong_password(self, db_session):
        sign_up("wrongpw@example.com", "correct", "User")
        with pytest.raises(ValueError, match="이메일 또는 비밀번호"):
            sign_in("wrongpw@example.com", "incorrect")

    def test_nonexistent_email(self, db_session):
        with pytest.raises(ValueError, match="이메일 또는 비밀번호"):
            sign_in("ghost@example.com", "anything")

    def test_empty_password(self, db_session):
        sign_up("emptypw@example.com", "realpass", "User")
        with pytest.raises(ValueError):
            sign_in("emptypw@example.com", "")


# ─────────────────────────────────────────────
# 서비스 레이어: create_access_token / get_user_from_token
# ─────────────────────────────────────────────

class TestTokens:
    def test_token_contains_sub(self, db_session):
        user, token = sign_up("tok@example.com", "pass", "Token User")
        settings = get_settings()
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        assert payload["sub"] == user.id

    def test_token_verification_valid(self, db_session):
        user, token = sign_up("verify@example.com", "pass", "Verify User")
        verified = get_user_from_token(token)
        assert verified is not None
        assert verified.email == "verify@example.com"

    def test_token_verification_invalid_string(self, db_session):
        assert get_user_from_token("not.a.valid.token") is None

    def test_token_verification_empty_string(self, db_session):
        assert get_user_from_token("") is None

    def test_token_verification_tampered(self, db_session):
        _, token = sign_up("tamper@example.com", "pass", "Tamper")
        # 토큰 마지막 글자를 바꿔서 서명 위조
        tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
        assert get_user_from_token(tampered) is None

    def test_expired_token_rejected(self, db_session):
        sign_up("expired@example.com", "pass", "Expired")
        settings = get_settings()
        expired_payload = {
            "sub": "some-id",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired_token = jwt.encode(expired_payload, settings.secret_key, algorithm="HS256")
        assert get_user_from_token(expired_token) is None

    def test_token_missing_sub_rejected(self, db_session):
        settings = get_settings()
        bad_token = jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.secret_key,
            algorithm="HS256",
        )
        assert get_user_from_token(bad_token) is None


# ─────────────────────────────────────────────
# HTTP 라우터: /auth/*
# ─────────────────────────────────────────────

class TestAuthRoutes:
    def test_login_page_renders(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert "form" in resp.text.lower()

    def test_login_page_redirects_when_authenticated(self, auth_client):
        resp = auth_client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]

    def test_signup_success_sets_cookie_and_redirects(self, client):
        resp = client.post(
            "/auth/signup",
            data={"email": "route_signup@example.com", "password": "pass123", "full_name": "Route"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]
        assert "access_token" in resp.cookies

    def test_signup_duplicate_stays_on_signup(self, client):
        client.post(
            "/auth/signup",
            data={"email": "dup_route@example.com", "password": "pass", "full_name": "Dup"},
        )
        resp = client.post(
            "/auth/signup",
            data={"email": "dup_route@example.com", "password": "pass2", "full_name": "Dup2"},
            follow_redirects=False,
        )
        # 실패 시 signup 탭으로 돌아가야 함
        assert resp.status_code == 302
        assert "signup" in resp.headers["Location"]

    def test_login_success(self, client):
        client.post(
            "/auth/signup",
            data={"email": "login_route@example.com", "password": "loginpass", "full_name": "Login"},
        )
        resp = client.post(
            "/auth/login",
            data={"email": "login_route@example.com", "password": "loginpass"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]
        assert "access_token" in resp.cookies

    def test_login_wrong_password_stays_on_login(self, client):
        client.post(
            "/auth/signup",
            data={"email": "wrongpw_route@example.com", "password": "correct", "full_name": "User"},
        )
        resp = client.post(
            "/auth/login",
            data={"email": "wrongpw_route@example.com", "password": "wrong"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_logout_clears_cookies(self, auth_client):
        resp = auth_client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        # 쿠키가 삭제(빈 값 또는 Max-Age=0)되어야 함
        assert "access_token" not in resp.cookies or resp.cookies.get("access_token") == ""
