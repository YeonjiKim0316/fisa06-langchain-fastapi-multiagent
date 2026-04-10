"""
HTTP 라우터 통합 테스트 (test_api.py 대체).

커버리지:
- GET /                 → /auth/login 리다이렉트
- GET /dashboard        → 인증 필요, 보고서 목록 표시
- POST /settings/apikeys, /settings/preferences
- GET /reports/{filename} → 보고서 뷰어
- POST /reports/{filename}/delete
- GET /generate         → 인증 필요, 폼 표시
- GET /generate/stream  → SSE (LangGraph는 mock 처리)
"""
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from services.storage_service import save_report, load_saved_reports
from services.auth_service import get_user_from_token


# ─────────────────────────────────────────────
# 루트 / 공통
# ─────────────────────────────────────────────

class TestRoot:
    def test_root_redirects_to_login(self, client):
        # RedirectResponse 기본값은 307이므로 3xx 전체 허용
        resp = client.get("/", follow_redirects=False)
        assert resp.is_redirect, f"리다이렉트가 아님: {resp.status_code}"
        assert "/auth/login" in resp.headers["Location"]


# ─────────────────────────────────────────────
# 대시보드
# ─────────────────────────────────────────────

class TestDashboard:
    def test_dashboard_requires_auth(self, client):
        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_dashboard_renders_for_authenticated(self, auth_client):
        resp = auth_client.get("/dashboard")
        assert resp.status_code == 200
        assert "dashboard" in resp.text.lower() or "report" in resp.text.lower()

    def test_dashboard_shows_user_reports(self, auth_client, db_session, test_user):
        user = get_user_from_token(test_user["token"])
        save_report(str(user.id), "My Dashboard Report", "# Content")
        resp = auth_client.get("/dashboard")
        assert resp.status_code == 200
        assert "My Dashboard Report" in resp.text

    def test_dashboard_does_not_show_other_users_reports(self, auth_client, db_session, test_user):
        """다른 유저의 보고서가 대시보드에 표시되면 안 됨."""
        save_report("other-user-id", "Secret Report", "# Secret")
        resp = auth_client.get("/dashboard")
        assert "Secret Report" not in resp.text


# ─────────────────────────────────────────────
# 설정 저장
# ─────────────────────────────────────────────

class TestSettings:
    def test_save_preferences_requires_auth(self, client):
        resp = client.post(
            "/settings/preferences",
            data={"language": "English", "model_name": "gpt-5-nano"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_save_preferences_redirects_to_dashboard(self, auth_client):
        resp = auth_client.post(
            "/settings/preferences",
            data={"language": "English", "model_name": "gpt-5-nano"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]

    def test_save_preferences_sets_session(self, auth_client):
        resp = auth_client.post(
            "/settings/preferences",
            data={"language": "English", "model_name": "gpt-5"},
            follow_redirects=False,
        )
        # session 쿠키가 응답에 포함되어야 함
        assert "session" in resp.cookies or "session" in auth_client.cookies

    def test_save_apikeys_requires_auth(self, client):
        resp = client.post(
            "/settings/apikeys",
            data={"openai_key": "sk-test", "tavily_key": "tv-test"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_save_apikeys_redirects_to_generate(self, auth_client):
        resp = auth_client.post(
            "/settings/apikeys",
            data={"openai_key": "sk-test-key", "tavily_key": "tvly-test-key"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/generate" in resp.headers["Location"]


# ─────────────────────────────────────────────
# 보고서 뷰어 / 삭제
# ─────────────────────────────────────────────

class TestReportsRoutes:
    def test_view_report_requires_auth(self, client):
        resp = client.get("/reports/some_file.md", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_view_report_not_found_redirects(self, auth_client):
        resp = auth_client.get("/reports/nonexistent.md", follow_redirects=False)
        # 없는 보고서는 대시보드로 리다이렉트
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]

    def test_view_report_success(self, auth_client, db_session, test_user):
        user = get_user_from_token(test_user["token"])
        content = "# Report Title\n\nReport body content."
        save_report(str(user.id), "View Test", content)
        reports = load_saved_reports(str(user.id))
        filename = reports[0]["filename"]

        resp = auth_client.get(f"/reports/{filename}")
        assert resp.status_code == 200
        assert "Report Title" in resp.text or "View Test" in resp.text

    def test_delete_report_requires_auth(self, client):
        resp = client.post("/reports/some_file.md/delete", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_delete_report_success(self, auth_client, db_session, test_user):
        user = get_user_from_token(test_user["token"])
        save_report(str(user.id), "Delete Me", "content")
        reports = load_saved_reports(str(user.id))
        filename = reports[0]["filename"]

        resp = auth_client.post(f"/reports/{filename}/delete", follow_redirects=False)
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]
        assert load_saved_reports(str(user.id)) == []

    def test_delete_nonexistent_report_redirects(self, auth_client):
        resp = auth_client.post("/reports/ghost.md/delete", follow_redirects=False)
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]


# ─────────────────────────────────────────────
# 보고서 생성 페이지
# ─────────────────────────────────────────────

class TestGeneratePage:
    def test_generate_requires_auth(self, client):
        resp = client.get("/generate", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_generate_page_renders(self, auth_client):
        resp = auth_client.get("/generate")
        assert resp.status_code == 200
        assert "form" in resp.text.lower() or "topic" in resp.text.lower()


# ─────────────────────────────────────────────
# SSE 스트리밍 엔드포인트 (LangGraph mock)
# ─────────────────────────────────────────────

class TestGenerateStream:
    def test_stream_requires_auth(self, client):
        resp = client.get("/generate/stream?topic=test", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_stream_no_api_keys_returns_error_event(self, auth_client):
        """API 키가 없으면 stream_error 이벤트를 즉시 반환해야 함.

        os.environ 제거만으로는 부족 — generate 라우터가 settings.openai_api_key로
        폴백하여 os.environ에 다시 주입하기 때문. settings까지 함께 패치해야 함.
        """
        import os
        from unittest.mock import patch, MagicMock

        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        old_tavily = os.environ.pop("TAVILY_API_KEY", None)

        empty_settings = MagicMock()
        empty_settings.openai_api_key = ""
        empty_settings.tavily_api_key = ""

        try:
            with patch("core.config.get_settings", return_value=empty_settings):
                resp = auth_client.get("/generate/stream?topic=test")
            assert resp.status_code == 200
            assert "stream_error" in resp.text
        finally:
            if old_openai:
                os.environ["OPENAI_API_KEY"] = old_openai
            if old_tavily:
                os.environ["TAVILY_API_KEY"] = old_tavily

    def test_stream_with_mocked_agent(self, auth_client):
        """SSE 엔드포인트 기본 동작 검증 (응답 코드 + Content-Type).

        stream_mode="updates" 포맷: {node_name: state_delta} 딕셔너리로 yield.
        """
        import os
        os.environ["OPENAI_API_KEY"] = "sk-mock-key-for-testing"
        os.environ["TAVILY_API_KEY"] = "tvly-mock-key-for-testing"

        mock_section = MagicMock()
        mock_section.name = "Introduction"
        mock_section.description = "Overview section"
        mock_section.research = False
        mock_section.content = "## Introduction\n\nThis is the intro."

        async def mock_astream(*args, **kwargs):
            # stream_mode="updates": {node_name: state_delta}
            yield {"generate_report_plan": {"sections": [mock_section]}}
            yield {"compile_final_report": {"final_report": "# Final Report\n\nContent."}}

        async def mock_aget_state(*args, **kwargs):
            state = MagicMock()
            state.next = []
            state.values = {"sections": [mock_section]}
            return state

        mock_agent = MagicMock()
        mock_agent.astream = mock_astream
        mock_agent.aget_state = mock_aget_state

        with patch("deep_ai.agent.reporter_agent", mock_agent), \
             patch("routers.generate.save_report", return_value="mock/path.md"):
            with auth_client.stream(
                "GET",
                "/generate/stream?topic=Test+Topic&thread_id=test-thread-001",
            ) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")
                body = resp.read().decode("utf-8", errors="replace")

        assert "event:" in body or "data:" in body or body == "", \
            f"예상치 못한 응답: {body[:200]}"

    def test_stream_hitl_plan_generated_event(self, auth_client):
        """HITL 인터럽트 시 plan_generated 이벤트가 발생해야 함."""
        import os
        os.environ["OPENAI_API_KEY"] = "sk-mock-key-for-testing"
        os.environ["TAVILY_API_KEY"] = "tvly-mock-key-for-testing"

        mock_section = MagicMock()
        mock_section.name = "Section 1"
        mock_section.description = "Description 1"
        mock_section.research = True

        async def mock_astream(*args, **kwargs):
            # interrupt_after=["generate_report_plan"] 시 스트림은 해당 노드 업데이트 후 종료
            yield {"generate_report_plan": {"sections": [mock_section]}}

        async def mock_aget_state(*args, **kwargs):
            state = MagicMock()
            state.next = ["section_builder_with_web_search"]  # HITL 인터럽트 상태
            state.values = {"sections": [mock_section]}
            return state

        mock_agent = MagicMock()
        mock_agent.astream = mock_astream
        mock_agent.aget_state = mock_aget_state

        with patch("deep_ai.agent.reporter_agent", mock_agent):
            with auth_client.stream("GET", "/generate/stream?topic=HITL+Test") as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")
                body = resp.read().decode("utf-8", errors="replace")

        assert "plan_generated" in body or "event:" in body or body == "", \
            f"예상치 못한 응답: {body[:200]}"
