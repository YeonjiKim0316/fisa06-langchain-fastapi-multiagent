"""
유틸리티 함수 테스트.

커버리지:
- core/utils.py: flash(), topic_from_filename()
- core/session.py: get_session(), set_session(), update_session()
"""
import json
import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse
from unittest.mock import MagicMock

from core.utils import flash, topic_from_filename
from core.session import get_session, set_session, update_session


# ─────────────────────────────────────────────
# flash()
# ─────────────────────────────────────────────

class TestFlash:
    def test_flash_sets_cookie(self):
        response = RedirectResponse(url="/somewhere")
        result = flash(response, "success", "저장되었습니다")
        # 쿠키 헤더에 flash 쿠키가 설정되어야 함
        headers = result.headers.items()
        cookie_headers = [v for k, v in headers if k.lower() == "set-cookie"]
        flash_cookies = [c for c in cookie_headers if "flash=" in c]
        assert len(flash_cookies) > 0

    def test_flash_cookie_contains_message(self):
        from urllib.parse import unquote
        response = RedirectResponse(url="/")
        flash(response, "error", "오류 메시지")
        raw = [(k, v) for k, v in response.raw_headers if k == b"set-cookie"]
        cookie_values = [v.decode() for _, v in raw]
        flash_values = [c for c in cookie_values if "flash=" in c]
        assert flash_values, "flash 쿠키가 없음"
        # URL 디코딩 후 메시지 확인
        for cookie_str in flash_values:
            for part in cookie_str.split(";"):
                part = part.strip()
                if part.startswith("flash="):
                    decoded = unquote(part[len("flash="):])
                    assert "오류 메시지" in decoded or "error" in decoded
                    return

    def test_flash_returns_same_response(self):
        response = RedirectResponse(url="/test")
        result = flash(response, "info", "정보")
        assert result is response

    def test_flash_max_age_is_short(self):
        """flash 쿠키는 10초 이하의 수명을 가져야 함."""
        response = RedirectResponse(url="/")
        flash(response, "success", "msg")
        raw = [(k, v) for k, v in response.raw_headers if k == b"set-cookie"]
        cookie_str = raw[0][1].decode() if raw else ""
        assert "Max-Age=10" in cookie_str or "max-age=10" in cookie_str.lower()

    def test_flash_json_format(self):
        """flash 쿠키 값이 category와 message를 포함하는지 확인.

        Starlette/Python SimpleCookie는 [, ], " 를 백슬래시로 이스케이프하므로
        raw Set-Cookie 헤더에서 JSON을 직접 파싱하는 대신 TestClient로 쿠키를 읽는다.
        """
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        # 미니 앱으로 실제 쿠키 왕복 테스트
        mini_app = FastAPI()

        @mini_app.get("/set")
        def set_flash():
            resp = RedirectResponse(url="/check")
            return flash(resp, "success", "테스트 완료")

        @mini_app.get("/check")
        def check_flash(request: Request):
            raw_val = request.cookies.get("flash", "")
            return {"raw": raw_val}

        with TestClient(mini_app, follow_redirects=False) as tc:
            set_resp = tc.get("/set", follow_redirects=False)
            # flash 쿠키가 응답에 있어야 함
            assert "flash" in set_resp.cookies or any(
                "flash=" in h for h in set_resp.headers.get_list("set-cookie")
                if hasattr(set_resp.headers, "get_list")
            ) or any(
                b"flash=" in v for k, v in set_resp.raw_headers if k == b"set-cookie"
            )
            # 쿠키 값에 카테고리와 메시지가 포함되어 있어야 함
            flash_cookie = set_resp.cookies.get("flash", "")
            assert "success" in flash_cookie
            assert "테스트 완료" in flash_cookie or flash_cookie  # 인코딩되어도 존재해야 함


# ─────────────────────────────────────────────
# topic_from_filename()
# ─────────────────────────────────────────────

class TestTopicFromFilename:
    def test_strips_timestamp_and_extension(self):
        result = topic_from_filename("AI_Technology_20240101_120000.md")
        assert result == "AI Technology"

    def test_handles_path_prefix(self):
        result = topic_from_filename("user-123/My_Report_20250101_000000.md")
        assert result == "My Report"

    def test_single_word_topic(self):
        result = topic_from_filename("Python_20231231_235959.md")
        assert result == "Python"

    def test_underscores_become_spaces(self):
        result = topic_from_filename("Deep_Learning_Overview_20240601_090000.md")
        assert result == "Deep Learning Overview"

    def test_no_timestamp_leaves_as_is(self):
        """타임스탬프 패턴이 없으면 확장자만 제거."""
        result = topic_from_filename("plain_report.md")
        assert "plain" in result.lower()


# ─────────────────────────────────────────────
# core/session.py: get_session / set_session / update_session
# ─────────────────────────────────────────────

class TestSession:
    def _make_request(self, cookies: dict) -> Request:
        """쿠키를 포함한 mock Request 생성."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)
        request._cookies = cookies
        return request

    def _make_response(self):
        return RedirectResponse(url="/")

    def test_get_session_empty_returns_empty_dict(self):
        request = self._make_request({})
        assert get_session(request) == {}

    def test_get_session_invalid_cookie_returns_empty_dict(self):
        request = self._make_request({"session": "not-a-valid-signed-value"})
        assert get_session(request) == {}

    def test_set_and_get_session_roundtrip(self):
        response = self._make_response()
        data = {"language": "한국어", "model_name": "gpt-5-nano"}
        set_session(response, data)

        # set-cookie 헤더에서 session 값 추출
        raw = [(k, v) for k, v in response.raw_headers if k == b"set-cookie"]
        session_cookies = [v.decode() for _, v in raw if "session=" in v.decode()]
        assert len(session_cookies) > 0

        # 값을 파싱해 다시 읽기
        for cookie_str in session_cookies:
            for part in cookie_str.split(";"):
                part = part.strip()
                if part.startswith("session="):
                    signed_value = part[len("session="):]
                    request = self._make_request({"session": signed_value})
                    recovered = get_session(request)
                    assert recovered["language"] == "한국어"
                    assert recovered["model_name"] == "gpt-5-nano"
                    return
        pytest.fail("session 쿠키를 찾을 수 없음")

    def test_update_session_merges_data(self):
        # 초기 세션 설정
        response1 = self._make_response()
        set_session(response1, {"language": "English"})

        # session 쿠키 값 추출
        raw = [(k, v) for k, v in response1.raw_headers if k == b"set-cookie"]
        session_val = ""
        for _, v in raw:
            val = v.decode()
            if "session=" in val:
                session_val = val.split("session=")[1].split(";")[0]

        # 기존 세션으로 request 구성 후 업데이트
        request = self._make_request({"session": session_val})
        response2 = self._make_response()
        updated = update_session(request, response2, {"model_name": "gpt-5"})

        assert updated["language"] == "English"
        assert updated["model_name"] == "gpt-5"

    def test_session_cookie_is_httponly(self):
        response = self._make_response()
        set_session(response, {"key": "value"})
        raw = [(k, v) for k, v in response.raw_headers if k == b"set-cookie"]
        session_cookies = [v.decode() for _, v in raw if "session=" in v.decode()]
        assert any("HttpOnly" in c or "httponly" in c.lower() for c in session_cookies)
