"""
PDF 서비스 및 라우터 테스트.

커버리지:
- generate_pdf: 유효한 PDF 바이트 반환 (%PDF- 헤더)
- generate_pdf: 한글 콘텐츠 처리
- generate_pdf: 마크다운 테이블 처리
- generate_pdf: 코드블록 처리
- generate_pdf: 빈 콘텐츠 처리
- POST /pdf/generate: 인증 필요, 정상 응답
- GET /pdf/reports/{filename}/pdf: 저장된 보고서 PDF 다운로드
- GET /pdf/reports/{filename}/markdown: 마크다운 다운로드
"""
import pytest
from services.pdf_service import generate_pdf
from services.storage_service import save_report, load_saved_reports


# ─────────────────────────────────────────────
# generate_pdf 유닛 테스트
# ─────────────────────────────────────────────

class TestGeneratePdf:
    def test_returns_bytes(self):
        result = generate_pdf("# Hello\n\nSimple content.", "Test Report")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_valid_pdf_header(self):
        """ReportLab이 생성하는 PDF는 항상 %PDF- 헤더로 시작해야 함."""
        result = generate_pdf("# Test\n\nContent here.", "My Topic")
        assert result[:5] == b"%PDF-"

    def test_korean_content(self):
        korean_md = "# 한국어 제목\n\n한국어 본문 내용입니다. AI 기술 발전에 대해 설명합니다."
        result = generate_pdf(korean_md, "한국어 보고서")
        assert result[:5] == b"%PDF-"
        assert len(result) > 100

    def test_markdown_table(self):
        table_md = (
            "# Report\n\n"
            "| Column A | Column B |\n"
            "|----------|----------|\n"
            "| Value 1  | Value 2  |\n"
            "| Value 3  | Value 4  |\n"
        )
        result = generate_pdf(table_md, "Table Report")
        assert result[:5] == b"%PDF-"

    def test_code_block(self):
        code_md = (
            "# Code Example\n\n"
            "```python\n"
            "def hello():\n"
            "    print('Hello, World!')\n"
            "```\n"
        )
        result = generate_pdf(code_md, "Code Report")
        assert result[:5] == b"%PDF-"

    def test_empty_content(self):
        """빈 마크다운도 오류 없이 처리되어야 함."""
        result = generate_pdf("", "Empty Report")
        assert result[:5] == b"%PDF-"

    def test_escaped_dollar_sign(self):
        """$ 기호 이스케이프 처리 확인 (generate_pdf는 직접 처리 안 하지만, 오류 없이 통과해야 함)."""
        md = "# Price\n\nCost is \\$25.5 per unit."
        result = generate_pdf(md, "Price Report")
        assert result[:5] == b"%PDF-"

    def test_heading_levels(self):
        md = "# H1\n## H2\n### H3\n\nParagraph text."
        result = generate_pdf(md, "Headings")
        assert result[:5] == b"%PDF-"

    def test_bullet_list(self):
        md = "# List\n\n- Item 1\n- Item 2\n- Item 3\n"
        result = generate_pdf(md, "List Report")
        assert result[:5] == b"%PDF-"


# ─────────────────────────────────────────────
# PDF 라우터 테스트
# ─────────────────────────────────────────────

class TestPdfRoutes:
    def test_pdf_generate_requires_auth(self, client):
        resp = client.post(
            "/pdf/generate",
            data={"topic": "Test", "content": "# Test\nContent"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_pdf_generate_returns_pdf(self, auth_client):
        resp = auth_client.post(
            "/pdf/generate",
            data={"topic": "Test Topic", "content": "# Test\n\nSome content here."},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content[:5] == b"%PDF-"

    def test_pdf_generate_filename_in_header(self, auth_client):
        resp = auth_client.post(
            "/pdf/generate",
            data={"topic": "My Report", "content": "# Title\n\nBody."},
        )
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "_report.pdf" in cd

    def test_pdf_from_storage_requires_auth(self, client):
        resp = client.get("/pdf/reports/some_file.md/pdf", follow_redirects=False)
        assert resp.status_code == 302

    def test_pdf_from_storage_not_found(self, auth_client, db_session):
        resp = auth_client.get("/pdf/reports/nonexistent_file.md/pdf")
        assert resp.status_code == 404

    def test_pdf_from_storage_success(self, auth_client, db_session, test_user):
        """저장된 보고서의 PDF 다운로드."""
        from services.auth_service import get_user_from_token
        user = get_user_from_token(test_user["token"])
        content = "# Saved Report\n\nThis is the content."
        save_report(str(user.id), "Saved Topic", content)
        reports = load_saved_reports(str(user.id))
        filename = reports[0]["filename"]

        resp = auth_client.get(f"/pdf/reports/{filename}/pdf")
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_markdown_download_success(self, auth_client, db_session, test_user):
        """저장된 보고서의 마크다운 다운로드."""
        from services.auth_service import get_user_from_token
        user = get_user_from_token(test_user["token"])
        content = "# MD Download\n\nMarkdown content."
        save_report(str(user.id), "MD Topic", content)
        reports = load_saved_reports(str(user.id))
        filename = reports[0]["filename"]

        resp = auth_client.get(f"/pdf/reports/{filename}/markdown")
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert resp.text == content

    def test_markdown_download_not_found(self, auth_client):
        resp = auth_client.get("/pdf/reports/ghost.md/markdown")
        assert resp.status_code == 404
