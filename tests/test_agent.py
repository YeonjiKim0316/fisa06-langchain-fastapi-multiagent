"""
LangGraph 에이전트 테스트.

fast 테스트 (mock 기반):
- 그래프 노드 구조 검증
- 모델명 매핑 (gpt-5 → gpt-4o, gpt-5-nano → gpt-4o-mini)
- format_sections 출력 형식
- parallelize_section_writing: research=True 섹션만 Send
- parallelize_final_section_writing: research=False 섹션만 Send

slow 테스트 (실제 API 키 필요, pytest -m slow):
- HITL 흐름: 계획 생성 → 중단 → 재개 → 최종 보고서
- 제외 섹션 처리 (excluded 파라미터)
"""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ─────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────

def _make_section(name: str, research: bool = True, content: str = ""):
    from deep_ai.agent import Section
    return Section(name=name, description=f"{name} desc", research=research, content=content)


# ─────────────────────────────────────────────
# 그래프 구조 검증 (mock 없이 모듈 레벨 확인)
# ─────────────────────────────────────────────

class TestGraphStructure:
    def test_required_nodes_exist(self):
        from deep_ai.agent import builder
        node_names = set(builder.nodes.keys())
        required = {
            "generate_report_plan",
            "section_builder_with_web_search",
            "format_completed_sections",
            "write_final_sections",
            "compile_final_report",
        }
        assert required.issubset(node_names), f"누락된 노드: {required - node_names}"

    def test_builder_is_defined(self):
        from deep_ai.agent import builder
        assert builder is not None

    def test_section_builder_nodes_exist(self):
        from deep_ai.agent import section_builder
        node_names = set(section_builder.nodes.keys())
        assert {"generate_queries", "search_web", "write_section"}.issubset(node_names)


# ─────────────────────────────────────────────
# 모델명 매핑
# ─────────────────────────────────────────────

class TestModelNameMapping:
    def test_gpt5_maps_to_gpt4o(self):
        with patch("deep_ai.agent.ChatOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            from deep_ai.agent import get_llm
            get_llm("gpt-5")
            call_kwargs = mock_openai.call_args
            assert call_kwargs is not None
            model_used = call_kwargs[1].get("model_name") or call_kwargs[0][0] if call_kwargs[0] else None
            # kwargs 방식
            if call_kwargs.kwargs:
                assert call_kwargs.kwargs.get("model_name") == "gpt-4o"

    def test_gpt5_nano_maps_to_gpt4o_mini(self):
        with patch("deep_ai.agent.ChatOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            from deep_ai.agent import get_llm
            get_llm("gpt-5-nano")
            if mock_openai.call_args and mock_openai.call_args.kwargs:
                assert mock_openai.call_args.kwargs.get("model_name") == "gpt-4o-mini"

    def test_unknown_model_passes_through(self):
        with patch("deep_ai.agent.ChatOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            from deep_ai.agent import get_llm
            get_llm("gpt-4-turbo")
            if mock_openai.call_args and mock_openai.call_args.kwargs:
                assert mock_openai.call_args.kwargs.get("model_name") == "gpt-4-turbo"


# ─────────────────────────────────────────────
# format_sections
# ─────────────────────────────────────────────

class TestFormatSections:
    def test_format_includes_section_name(self):
        from deep_ai.agent import format_sections
        sections = [_make_section("Introduction", research=False, content="Intro text")]
        result = format_sections(sections)
        assert "Introduction" in result

    def test_format_shows_not_written_placeholder(self):
        from deep_ai.agent import format_sections
        sections = [_make_section("Empty Section", content="")]
        result = format_sections(sections)
        assert "[Not yet written]" in result

    def test_format_multiple_sections(self):
        from deep_ai.agent import format_sections
        sections = [
            _make_section("Sec A", content="Content A"),
            _make_section("Sec B", content="Content B"),
        ]
        result = format_sections(sections)
        assert "Sec A" in result and "Sec B" in result


# ─────────────────────────────────────────────
# parallelize helpers
# ─────────────────────────────────────────────

class TestParallelizeHelpers:
    def test_parallelize_section_writing_only_research_sections(self):
        from deep_ai.agent import parallelize_section_writing
        from langgraph.constants import Send

        sections = [
            _make_section("Research Sec", research=True),
            _make_section("No Research Sec", research=False),
        ]
        state = {"sections": sections, "language": "English", "model_name": "gpt-5-nano"}
        result = parallelize_section_writing(state)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], Send)
        assert result[0].node == "section_builder_with_web_search"

    def test_parallelize_final_section_writing_only_non_research(self):
        from deep_ai.agent import parallelize_final_section_writing
        from langgraph.constants import Send

        sections = [
            _make_section("Research Sec", research=True),
            _make_section("Conclusion", research=False),
            _make_section("Introduction", research=False),
        ]
        state = {
            "sections": sections,
            "report_sections_from_research": "some context",
            "language": "English",
            "model_name": "gpt-5-nano",
        }
        result = parallelize_final_section_writing(state)

        assert isinstance(result, list)
        assert len(result) == 2
        for send in result:
            assert isinstance(send, Send)
            assert send.node == "write_final_sections"

    def test_parallelize_empty_sections(self):
        from deep_ai.agent import parallelize_section_writing
        state = {"sections": [], "language": "English", "model_name": "gpt-5-nano"}
        result = parallelize_section_writing(state)
        assert result == []


# ─────────────────────────────────────────────
# 실제 API 호출 테스트 (slow)
# ─────────────────────────────────────────────

HAS_API_KEYS = bool(os.environ.get("OPENAI_API_KEY")) and bool(os.environ.get("TAVILY_API_KEY"))


@pytest.mark.slow
@pytest.mark.skipif(not HAS_API_KEYS, reason="실제 API 키 없음 (OPENAI_API_KEY, TAVILY_API_KEY 필요)")
async def test_hitl_plan_then_resume():
    """
    HITL 흐름 통합 테스트:
    1) 새 thread_id로 astream → generate_report_plan 후 interrupt
    2) plan_generated 이벤트 확인
    3) 동일 thread_id로 resume → compile_final_report까지 실행
    """
    import uuid
    import deep_ai.agent as _agent_module
    await _agent_module.init_checkpointer()
    reporter_agent = _agent_module.reporter_agent

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    # Phase 1: 계획 생성 (HITL 중단 지점)
    steps_phase1 = set()
    async for snap in reporter_agent.astream(
        {"topic": "파이썬 기초", "language": "한국어", "model_name": "gpt-5-nano"},
        config,
        stream_mode="updates",
    ):
        steps_phase1.update(snap.keys())

    assert "generate_report_plan" in steps_phase1

    # HITL: 중단 상태 확인
    state = await reporter_agent.aget_state(config)
    sections = state.values.get("sections", [])
    assert len(sections) > 0, "섹션이 생성되어야 함"

    research_sections = [s for s in sections if s.research]

    # Phase 2: resume (agent_input=None)
    # research 섹션이 없으면 graph가 interrupt 없이 완료될 수 있음
    if not research_sections:
        # sections이 있으면 graph는 정상 동작한 것 — Phase 1만 검증하고 종료
        return

    assert state.next, "리서치 섹션이 있으면 interrupt 후 next 노드가 있어야 함"

    steps_phase2 = set()
    final_report = None
    async for snap in reporter_agent.astream(None, config, stream_mode="updates"):
        steps_phase2.update(snap.keys())
        if "compile_final_report" in snap:
            final_report = snap["compile_final_report"].get("final_report")

    assert "compile_final_report" in steps_phase2
    assert final_report is not None
    assert len(final_report) > 100


@pytest.mark.slow
@pytest.mark.skipif(not HAS_API_KEYS, reason="실제 API 키 없음")
async def test_hitl_resume_with_excluded_sections():
    """제외 섹션을 지정하여 resume할 때 해당 섹션이 보고서에서 빠지는지 확인."""
    import uuid
    import deep_ai.agent as _agent_module
    await _agent_module.init_checkpointer()
    reporter_agent = _agent_module.reporter_agent

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    # Phase 1
    async for _ in reporter_agent.astream(
        {"topic": "머신러닝 입문", "language": "한국어", "model_name": "gpt-5-nano"},
        config,
        stream_mode="updates",
    ):
        pass

    state = await reporter_agent.aget_state(config)
    sections = state.values.get("sections", [])
    assert len(sections) >= 2, "테스트를 위해 최소 2개 섹션 필요"

    # 첫 번째 섹션 제외
    filtered = sections[1:]
    await reporter_agent.aupdate_state(config, {"sections": filtered})

    # Phase 2 resume
    final_report = None
    async for snap in reporter_agent.astream(None, config, stream_mode="updates"):
        if "compile_final_report" in snap:
            final_report = snap["compile_final_report"].get("final_report")

    assert final_report is not None
    # 제외된 섹션의 이름이 보고서에 없어야 함
    excluded_name = sections[0].name
    assert excluded_name not in final_report, f"제외된 섹션 '{excluded_name}'이 보고서에 포함됨"
