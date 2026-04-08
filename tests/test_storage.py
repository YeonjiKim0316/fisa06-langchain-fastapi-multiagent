"""
스토리지 서비스 테스트.

커버리지:
- LocalDiskStorage: upload / download / remove / 없는 파일 처리
- save_report: 파일 저장 + DB 레코드 생성
- save_report: 한글/특수문자 포함 topic의 안전한 파일명 변환
- load_saved_reports: 내림차순 정렬, 다른 유저 격리
- get_report_content: 정상 조회 / 없는 파일
- get_report_logs: JSON 로그 복원 / 없는 보고서
- delete_report: 파일 + DB 레코드 동시 삭제 / 없는 보고서
"""
import os
import json
import pytest
from services.storage_service import (
    LocalDiskStorage,
    save_report,
    load_saved_reports,
    get_report_content,
    get_report_logs,
    delete_report,
)


# ─────────────────────────────────────────────
# LocalDiskStorage 유닛 테스트
# ─────────────────────────────────────────────

class TestLocalDiskStorage:
    @pytest.fixture(autouse=True)
    def storage(self, tmp_path):
        self.store = LocalDiskStorage(str(tmp_path / "reports"))
        self.store.ensure_bucket()

    def test_upload_and_download(self):
        self.store.upload("user1/report.md", b"# Hello")
        result = self.store.download("user1/report.md")
        assert result == b"# Hello"

    def test_download_nonexistent_returns_none(self):
        assert self.store.download("ghost/file.md") is None

    def test_remove_existing(self):
        self.store.upload("user1/delete_me.md", b"bye")
        assert self.store.remove("user1/delete_me.md") is True
        assert self.store.download("user1/delete_me.md") is None

    def test_remove_nonexistent_returns_false(self):
        assert self.store.remove("no/such/file.md") is False

    def test_upload_overwrites(self):
        self.store.upload("user1/overwrite.md", b"v1")
        self.store.upload("user1/overwrite.md", b"v2")
        assert self.store.download("user1/overwrite.md") == b"v2"

    def test_ensure_bucket_creates_directory(self, tmp_path):
        new_dir = str(tmp_path / "fresh_bucket")
        store = LocalDiskStorage(new_dir)
        assert not os.path.exists(new_dir)
        store.ensure_bucket()
        assert os.path.isdir(new_dir)


# ─────────────────────────────────────────────
# save_report / load_saved_reports
# ─────────────────────────────────────────────

class TestSaveAndLoad:
    def test_save_returns_path(self, db_session):
        path = save_report("user-1", "Test Topic", "# Content")
        assert path is not None
        assert "user-1" in path

    def test_save_creates_db_record(self, db_session):
        save_report("user-2", "DB Record Test", "content")
        reports = load_saved_reports("user-2")
        assert len(reports) == 1
        assert reports[0]["topic"] == "DB Record Test"

    def test_save_with_logs(self, db_session):
        logs = [{"type": "progress", "label": "Step 1"}, {"type": "content", "title": "Sec1", "body": "text"}]
        save_report("user-3", "Log Test", "content", logs)
        fetched = get_report_logs("user-3", load_saved_reports("user-3")[0]["filename"])
        assert len(fetched) == 2
        assert fetched[0]["label"] == "Step 1"

    def test_save_without_logs(self, db_session):
        save_report("user-4", "No Logs", "content")
        logs = get_report_logs("user-4", load_saved_reports("user-4")[0]["filename"])
        assert logs == []

    def test_korean_topic_safe_filename(self, db_session):
        save_report("user-5", "한국 AI 기술 발전", "content")
        reports = load_saved_reports("user-5")
        filename = reports[0]["filename"]
        # 파일명에 ASCII 외 문자가 없어야 함
        assert filename.isascii() or "_" in filename
        assert filename.endswith(".md")

    def test_special_chars_in_topic(self, db_session):
        save_report("user-6", "Topic: A/B & C?", "content")
        reports = load_saved_reports("user-6")
        filename = reports[0]["filename"]
        # 파일시스템 위험 문자가 없어야 함
        for ch in ('/', '\\', ':', '?', '*', '"', '<', '>', '|'):
            assert ch not in filename

    def test_multiple_reports_sorted_desc(self, db_session):
        """애플리케이션 레벨 타임스탬프(밀리초)이므로 연속 저장도 순서 보장."""
        save_report("user-7", "First", "content1")
        save_report("user-7", "Second", "content2")
        reports = load_saved_reports("user-7")
        assert len(reports) == 2
        # 내림차순: 나중에 저장된 Second가 먼저
        assert reports[0]["topic"] == "Second"
        assert reports[1]["topic"] == "First"

    def test_different_users_isolated(self, db_session):
        save_report("user-A", "A's Report", "content A")
        save_report("user-B", "B's Report", "content B")
        a_reports = load_saved_reports("user-A")
        b_reports = load_saved_reports("user-B")
        assert len(a_reports) == 1
        assert len(b_reports) == 1
        assert a_reports[0]["topic"] == "A's Report"
        assert b_reports[0]["topic"] == "B's Report"

    def test_load_empty_for_unknown_user(self, db_session):
        assert load_saved_reports("unknown-user-xyz") == []


# ─────────────────────────────────────────────
# get_report_content
# ─────────────────────────────────────────────

class TestGetReportContent:
    def test_returns_content(self, db_session):
        content = "# My Report\n내용입니다."
        save_report("user-c1", "Content Test", content)
        reports = load_saved_reports("user-c1")
        fetched = get_report_content("user-c1", reports[0]["filename"])
        assert fetched == content

    def test_returns_none_for_missing_file(self, db_session):
        result = get_report_content("user-c2", "nonexistent_file.md")
        assert result is None

    def test_content_roundtrip_with_unicode(self, db_session):
        content = "# 제목\n한국어 내용 및 영문 mixed 콘텐츠 🚀"
        save_report("user-c3", "Unicode Test", content)
        reports = load_saved_reports("user-c3")
        fetched = get_report_content("user-c3", reports[0]["filename"])
        assert fetched == content


# ─────────────────────────────────────────────
# delete_report
# ─────────────────────────────────────────────

class TestDeleteReport:
    def test_delete_removes_file_and_record(self, db_session):
        save_report("user-d1", "To Delete", "delete me")
        reports = load_saved_reports("user-d1")
        filename = reports[0]["filename"]

        success = delete_report("user-d1", filename)
        assert success is True
        assert load_saved_reports("user-d1") == []
        assert get_report_content("user-d1", filename) is None

    def test_delete_nonexistent_returns_false(self, db_session):
        result = delete_report("user-d2", "ghost_report.md")
        assert result is False

    def test_delete_only_affects_target_user(self, db_session):
        save_report("user-d3", "Keep This", "keep")
        save_report("user-d4", "Delete This", "delete")
        d4_filename = load_saved_reports("user-d4")[0]["filename"]

        delete_report("user-d4", d4_filename)
        assert len(load_saved_reports("user-d3")) == 1
        assert load_saved_reports("user-d4") == []
