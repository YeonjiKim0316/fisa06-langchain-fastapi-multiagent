import os
import re as _re
import functools
from urllib.parse import urlparse as _urlparse

from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig

from deep_ai.prompts import (
    REPORT_PLAN_QUERY_GENERATOR_PROMPT,
    REPORT_PLAN_SECTION_GENERATOR_PROMPT,
    REPORT_SECTION_QUERY_GENERATOR_PROMPT,
    SECTION_WRITER_PROMPT,
    FINAL_SECTION_WRITER_PROMPT,
    DEFAULT_REPORT_STRUCTURE,
    LANGUAGE_INSTRUCTION,
)
from deep_ai.util import format_search_query_results, run_search_queries

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from typing_extensions import TypedDict
from pydantic import BaseModel, Field
import operator
from typing import Annotated, List


# ── Pydantic 구조화 출력 스키마 ──────────────────────────────────────────────

class Section(BaseModel):
    name: str = Field(description="보고서의 특정 섹션 이름.")
    description: str = Field(description="해당 섹션에서 다룰 주요 주제와 개념에 대한 간략한 개요.")
    research: bool = Field(description="해당 섹션에 대해 웹 검색을 수행할지 여부.")
    content: str = Field(description="해당 섹션의 내용.")


class Sections(BaseModel):
    sections: List[Section] = Field(description="전체 보고서의 모든 섹션 목록.")


class SearchQuery(BaseModel):
    search_query: str = Field(None, description="웹 검색 쿼리.")


class Queries(BaseModel):
    queries: List[SearchQuery] = Field(description="웹 검색 쿼리 목록.")


# ── 그래프 상태 정의 ──────────────────────────────────────────────────────────

class ReportStateInput(TypedDict):
    topic: str
    language: str       # "한국어" or "English"
    model_name: str     # UI 모델명 ("gpt-5" or "gpt-5-nano")


class ReportStateOutput(TypedDict):
    final_report: str


class ReportState(TypedDict):
    topic: str
    language: str
    model_name: str
    sections: list[Section]
    completed_sections: Annotated[list, operator.add]   # Send() API 누산기
    report_sections_from_research: str
    final_report: str


class SectionState(TypedDict):
    section: Section
    search_queries: list[SearchQuery]
    source_str: str
    report_sections_from_research: str
    completed_sections: list[Section]
    language: str
    model_name: str


class SectionOutputState(TypedDict):
    completed_sections: list[Section]


# ── LLM 팩토리 (lru_cache로 동일 (model, api_key) 인스턴스 재사용) ──────────

# UI 표시명 → 실제 OpenAI 모델명
MODEL_MAPPING: dict[str, str] = {
    "gpt-5": "gpt-5",
    "gpt-5-nano": "gpt-5-nano",
}


@functools.lru_cache(maxsize=8)
def _create_llm(real_model: str, api_key: str | None) -> ChatOpenAI:
    """실제 모델명과 API 키로 ChatOpenAI 인스턴스를 생성하고 캐싱한다."""
    kwargs: dict = {"model_name": real_model}
    if api_key:
        kwargs["api_key"] = api_key
    return ChatOpenAI(**kwargs)


def get_llm(model_name: str = "gpt-5-nano", api_key: str | None = None) -> ChatOpenAI:
    """UI 모델명을 실제 모델명으로 변환 후 캐싱된 LLM 인스턴스를 반환한다."""
    real_model = MODEL_MAPPING.get(model_name, model_name)
    return _create_llm(real_model, api_key)


# ── 헬퍼: config에서 API 키 추출 ─────────────────────────────────────────────

def _openai_key(config: RunnableConfig) -> str | None:
    """config.configurable 우선, 없으면 환경변수로 폴백.

    generate.py는 configurable에 키를 담아 전달하므로 os.environ 레이스 컨디션 없음.
    테스트나 스크립트처럼 직접 호출하는 경우에는 환경변수를 사용.
    """
    return config.get("configurable", {}).get("openai_api_key") or os.environ.get("OPENAI_API_KEY")


def _tavily_key(config: RunnableConfig) -> str | None:
    """config.configurable 우선, 없으면 환경변수로 폴백."""
    return config.get("configurable", {}).get("tavily_api_key") or os.environ.get("TAVILY_API_KEY")


# ── 보고서 플래너 에이전트 ───────────────────────────────────────────────────

async def generate_report_plan(state: ReportState, config: RunnableConfig):
    """보고서 전체 구성 계획을 생성한다."""
    topic = state["topic"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    lang_instr = LANGUAGE_INSTRUCTION.get(language, "")
    print("--- Generating Report Plan ---")

    llm = get_llm(model_name, api_key=_openai_key(config))

    # 1) 검색 쿼리 생성
    query_chain = REPORT_PLAN_QUERY_GENERATOR_PROMPT | llm.with_structured_output(Queries)
    results: Queries = await query_chain.ainvoke({
        "topic": topic,
        "report_organization": DEFAULT_REPORT_STRUCTURE,
        "number_of_queries": 3,
        "language_instruction": lang_instr,
    })
    query_list = [q.search_query for q in results.queries]

    # 2) 웹 검색
    search_docs = await run_search_queries(
        query_list,
        api_key=_tavily_key(config),
        num_results=4,
        include_raw_content=False,
    )
    search_context = (
        format_search_query_results(search_docs, include_raw_content=False)
        if search_docs
        else "No search results available."
    )

    # 3) 섹션 계획 생성
    section_chain = REPORT_PLAN_SECTION_GENERATOR_PROMPT | llm.with_structured_output(Sections)
    report_sections: Sections = await section_chain.ainvoke({
        "topic": topic,
        "report_organization": DEFAULT_REPORT_STRUCTURE,
        "search_context": search_context,
        "language_instruction": lang_instr,
    })

    print("--- Generating Report Plan Completed ---")
    return {"sections": report_sections.sections}


# ── 섹션 빌더: 검색 쿼리 생성 ────────────────────────────────────────────────

async def generate_queries(state: SectionState, config: RunnableConfig):
    """특정 보고서 섹션에 대한 검색 쿼리를 생성한다."""
    section = state["section"]
    model_name = state.get("model_name", "gpt-5-nano")
    print(f"--- Generating Search Queries for Section: {section.name} ---")

    llm = get_llm(model_name, api_key=_openai_key(config))
    query_chain = REPORT_SECTION_QUERY_GENERATOR_PROMPT | llm.with_structured_output(Queries)
    search_queries: Queries = await query_chain.ainvoke({
        "section_topic": section.description,
        "number_of_queries": 3,
    })

    print(f"--- Generating Search Queries for Section: {section.name} Completed ---")
    return {"search_queries": search_queries.queries}


# ── 섹션 빌더: 웹 검색 ───────────────────────────────────────────────────────

async def search_web(state: SectionState, config: RunnableConfig):
    """각 쿼리로 웹을 검색하고 포맷된 소스 문자열을 반환한다."""
    search_queries = state["search_queries"]
    print("--- Searching Web for Queries ---")

    query_list = [query.search_query for query in search_queries]
    search_docs = await run_search_queries(
        query_list,
        api_key=_tavily_key(config),
        num_results=2,
        include_raw_content=True,
    )
    search_context = format_search_query_results(
        search_docs, max_tokens=400, include_raw_content=True
    )

    print("--- Searching Web for Queries Completed ---")
    return {"source_str": search_context}


# ── 섹션 빌더: 작성 ──────────────────────────────────────────────────────────

async def write_section(state: SectionState, config: RunnableConfig):
    """보고서의 특정 섹션을 작성한다."""
    section = state["section"]
    source_str = state["source_str"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    print(f"--- Writing Section: {section.name} ---")

    llm = get_llm(model_name, api_key=_openai_key(config))
    chain = SECTION_WRITER_PROMPT | llm
    try:
        result = await chain.ainvoke({
            "section_title": section.name,
            "section_topic": section.description,
            "context": source_str,
            "language_instruction": LANGUAGE_INSTRUCTION.get(language, ""),
        })
        section.content = result.content
    except Exception as e:
        print(f"Error writing section '{section.name}': {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."

    print(f"--- Writing Section: {section.name} Completed ---")
    return {"completed_sections": [section]}


# ── 섹션 빌더 서브그래프 ─────────────────────────────────────────────────────

section_builder = StateGraph(SectionState, output_schema=SectionOutputState)
section_builder.add_node("generate_queries", generate_queries)
section_builder.add_node("search_web", search_web)
section_builder.add_node("write_section", write_section)

section_builder.add_edge(START, "generate_queries")
section_builder.add_edge("generate_queries", "search_web")
section_builder.add_edge("search_web", "write_section")
section_builder.add_edge("write_section", END)

section_builder_subagent = section_builder.compile()


# ── 병렬 섹션 작성 (map 단계) ────────────────────────────────────────────────

def parallelize_section_writing(state: ReportState):
    """research=True 섹션들을 Send() API로 병렬 실행한다."""
    return [
        Send(
            "section_builder_with_web_search",
            {
                "section": s,
                "language": state.get("language", "English"),
                "model_name": state.get("model_name", "gpt-5"),
            },
        )
        for s in state["sections"]
        if s.research
    ]


# ── 섹션 포맷터 ──────────────────────────────────────────────────────────────

def format_sections(sections: list[Section]) -> str:
    """보고서 섹션 목록을 하나의 텍스트 문자열로 포맷한다."""
    formatted_str = ""
    for idx, section in enumerate(sections, 1):
        formatted_str += f"""
{'='*60}
Section {idx}: {section.name}
{'='*60}
Description:
{section.description}
Requires Research:
{section.research}

Content:
{section.content if section.content else '[Not yet written]'}

"""
    return formatted_str


def format_completed_sections(state: ReportState):
    """완료된 섹션을 수집하고 최종 섹션 작성을 위한 컨텍스트로 포맷한다."""
    print("--- Formatting Completed Sections ---")
    completed_report_sections = format_sections(state["completed_sections"])
    print("--- Formatting Completed Sections Done ---")
    return {"report_sections_from_research": completed_report_sections}


# ── 최종 섹션 작성 (서론/결론) ───────────────────────────────────────────────

async def write_final_sections(state: SectionState, config: RunnableConfig):
    """웹 검색 없이 완료된 섹션을 컨텍스트로 활용해 서론/결론을 작성한다."""
    section = state["section"]
    completed_report_sections = state["report_sections_from_research"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    print(f"--- Writing Final Section: {section.name} ---")

    llm = get_llm(model_name, api_key=_openai_key(config))
    chain = FINAL_SECTION_WRITER_PROMPT | llm
    try:
        result = await chain.ainvoke({
            "section_title": section.name,
            "section_topic": section.description,
            "context": completed_report_sections,
            "language_instruction": LANGUAGE_INSTRUCTION.get(language, ""),
        })
        section.content = result.content
    except Exception as e:
        print(f"Error writing final section '{section.name}': {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."

    print(f"--- Writing Final Section: {section.name} Completed ---")
    return {"completed_sections": [section]}


# ── 병렬 최종 섹션 작성 ──────────────────────────────────────────────────────

def parallelize_final_section_writing(state: ReportState):
    """research=False 섹션들을 Send() API로 병렬 실행한다."""
    return [
        Send(
            "write_final_sections",
            {
                "section": s,
                "report_sections_from_research": state["report_sections_from_research"],
                "language": state.get("language", "English"),
                "model_name": state.get("model_name", "gpt-5-nano"),
            },
        )
        for s in state["sections"]
        if not s.research
    ]


# ── 최종 보고서 컴파일 ───────────────────────────────────────────────────────

def compile_final_report(state: ReportState):
    """완료된 모든 섹션을 원래 순서로 합쳐 최종 보고서를 생성한다."""
    sections = state["sections"]
    completed_sections = {s.name: s.content for s in state["completed_sections"]}
    print("--- Compiling Final Report ---")

    for section in sections:
        section.content = completed_sections.get(section.name, "")

    all_sections = "\n\n".join([s.content for s in sections])
    # 달러 기호 이스케이프 (이미 이스케이프된 것은 보존)
    formatted = all_sections.replace("\\$", "TEMP_PLACEHOLDER")
    formatted = formatted.replace("$", "\\$")
    formatted = formatted.replace("TEMP_PLACEHOLDER", "\\$")

    print("--- Compiling Final Report Done ---")
    return {"final_report": formatted}


# ── 메인 그래프 ──────────────────────────────────────────────────────────────

builder = StateGraph(ReportState, input_schema=ReportStateInput, output_schema=ReportStateOutput)

builder.add_node("generate_report_plan", generate_report_plan)
builder.add_node("section_builder_with_web_search", section_builder_subagent)
builder.add_node("format_completed_sections", format_completed_sections)
builder.add_node("write_final_sections", write_final_sections)
builder.add_node("compile_final_report", compile_final_report)

builder.add_edge(START, "generate_report_plan")
builder.add_conditional_edges(
    "generate_report_plan",
    parallelize_section_writing,
    ["section_builder_with_web_search"],
)
builder.add_edge("section_builder_with_web_search", "format_completed_sections")
builder.add_conditional_edges(
    "format_completed_sections",
    parallelize_final_section_writing,
    ["write_final_sections"],
)
builder.add_edge("write_final_sections", "compile_final_report")
builder.add_edge("compile_final_report", END)


# ── 체크포인터 초기화 ────────────────────────────────────────────────────────
# DATABASE_URL이 MySQL → AIOMySQLSaver
# 그 외(SQLite 등) → AsyncSqliteSaver

_ckpt_conn = None
reporter_agent = None  # main.py lifespan에서 init_checkpointer()로 초기화


def _parse_mysql_url(url: str) -> dict:
    """mysql+pymysql://user:pass@host:port/db 형태의 URL을 파싱해 dict로 반환."""
    clean = _re.sub(r"^mysql\+[^:]+://", "mysql://", url)
    parsed = _urlparse(clean)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "db": parsed.path.lstrip("/"),
    }


async def init_checkpointer():
    """앱 시작 시 DATABASE_URL에 따라 MySQL 또는 SQLite 체크포인터를 초기화한다."""
    global _ckpt_conn, reporter_agent

    from core.config import get_settings
    settings = get_settings()
    db_url = settings.database_url

    if db_url.startswith("mysql"):
        import aiomysql
        from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

        conn_params = _parse_mysql_url(db_url)
        _ckpt_conn = await aiomysql.connect(
            host=conn_params["host"],
            port=conn_params["port"],
            user=conn_params["user"],
            password=conn_params["password"],
            db=conn_params["db"],
            autocommit=True,
        )
        checkpointer = AIOMySQLSaver(_ckpt_conn)
        await checkpointer.setup()

        # MySQL 8.0 collation 통일 (utf8mb4_0900_ai_ci)
        _checkpoint_tables = [
            "checkpoint_migrations",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
        ]
        async with _ckpt_conn.cursor() as cur:
            for tbl in _checkpoint_tables:
                await cur.execute(
                    f"ALTER TABLE `{tbl}` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
    else:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        ckpt_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "checkpoints.db")
        )
        _ckpt_conn = await aiosqlite.connect(ckpt_path)
        checkpointer = AsyncSqliteSaver(_ckpt_conn)

    reporter_agent = builder.compile(
        checkpointer=checkpointer,
        interrupt_after=["generate_report_plan"],
    )


async def close_checkpointer():
    """앱 종료 시 DB 연결을 닫는다."""
    global _ckpt_conn
    if _ckpt_conn:
        try:
            if hasattr(_ckpt_conn, "ensure_closed"):
                await _ckpt_conn.ensure_closed()
            else:
                await _ckpt_conn.close()
        except Exception:
            pass
        _ckpt_conn = None
