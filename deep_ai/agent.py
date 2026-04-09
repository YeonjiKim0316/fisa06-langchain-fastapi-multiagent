from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from deep_ai.prompts import REPORT_PLAN_QUERY_GENERATOR_PROMPT, REPORT_PLAN_SECTION_GENERATOR_PROMPT, SECTION_WRITER_PROMPT, FINAL_SECTION_WRITER_PROMPT, REPORT_SECTION_QUERY_GENERATOR_PROMPT, DEFAULT_REPORT_STRUCTURE, LANGUAGE_INSTRUCTION
from deep_ai.util import format_search_query_results, run_search_queries

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from typing_extensions import TypedDict
from pydantic import BaseModel, Field
import operator
from typing import Annotated, List

class Section(BaseModel):
    name: str = Field(
        description="보고서의 특정 섹션 이름.",
    )
    description: str = Field(
        description="해당 섹션에서 다룰 주요 주제와 개념에 대한 간략한 개요.",
    )
    research: bool = Field(
        description="해당 섹션에 대해 웹 검색을 수행할지 여부."
    )
    content: str = Field(
        description="해당 섹션의 내용."
    )

class Sections(BaseModel):
    sections: List[Section] = Field(
        description="전체 보고서의 모든 섹션 목록.",
    )

class SearchQuery(BaseModel):
    search_query: str = Field(None, description="웹 검색 쿼리.")

class Queries(BaseModel):
    queries: List[SearchQuery] = Field(
        description="웹 검색 쿼리 목록.",
    )

class ReportStateInput(TypedDict):
    topic: str # 보고서 주제
    language: str # 출력 언어: "한국어" or "English"
    model_name: str # LLM 모델: "gpt-5" or "gpt-5-nano"

class ReportStateOutput(TypedDict):
    final_report: str # 최종 보고서

class ReportState(TypedDict):
    topic: str # 보고서 주제
    language: str # 출력 언어
    model_name: str # LLM 모델
    sections: list[Section] # 보고서 섹션 목록
    completed_sections: Annotated[list, operator.add] # Send() API
    report_sections_from_research: str # 최종 섹션 작성에 사용할 완료된 섹션 문자열
    final_report: str # 최종 보고서

class SectionState(TypedDict):
    section: Section # 보고서 섹션
    search_queries: list[SearchQuery] # 검색 쿼리 목록
    source_str: str # 웹 검색 결과를 포맷한 소스 문자열
    report_sections_from_research: str # 최종 섹션 작성에 사용할 완료된 섹션 문자열
    completed_sections: list[Section] # Send() API를 위해 외부 상태에 복제하는 최종 키
    language: str # 출력 언어
    model_name: str # LLM 모델

class SectionOutputState(TypedDict):
    completed_sections: list[Section] # Send() API를 위해 외부 상태에 복제하는 최종 키

# 임포트 시점이 아닌 필요할 때 LLM을 생성하는 함수
def get_llm(model_name="gpt-4o-mini"):
    """LLM 모델을 반환한다. 이름 매핑을 적용해 필요 시 초기화한다."""
    import os
    # 미래 호환 네이밍을 위한 커스텀 매핑
    model_mapping = {
        "gpt-5": "gpt-4o",
        "gpt-5-nano": "gpt-4o-mini",
    }
    real_model = model_mapping.get(model_name, model_name)
    api_key = os.environ.get("OPENAI_API_KEY")

    try:
        if api_key:
            return ChatOpenAI(model_name=real_model, temperature=0, api_key=api_key)
        return ChatOpenAI(model_name=real_model, temperature=0)
    except Exception as e:
        print(f"Error initializing OpenAI API with model {real_model}: {e}")
        raise RuntimeError("OpenAI API key not found or invalid. Please set the OPENAI_API_KEY environment variable.")

# 보고서 플래너 에이전트
async def generate_report_plan(state: ReportState):
    """보고서 전체 구성 계획을 생성한다."""
    topic = state["topic"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    print('--- Generating Report Plan ---')

    # 필요 시 LLM 초기화
    try:
        llm = get_llm(model_name)
    except Exception as e:
        print(f"Error initializing OpenAI API: {e}")
        return {"sections": []}

    report_structure = DEFAULT_REPORT_STRUCTURE
    number_of_queries = 3

    structured_llm = llm.with_structured_output(Queries)

    system_instructions_query = REPORT_PLAN_QUERY_GENERATOR_PROMPT.format(
        topic=topic,
        report_organization=report_structure,
        number_of_queries=number_of_queries
    )

    # 검색 쿼리 생성
    results = await structured_llm.ainvoke([
        SystemMessage(content=system_instructions_query),
        HumanMessage(content='Generate search queries that will help with planning the sections of the report.')
    ])

    # SearchQuery 객체를 문자열로 변환
    query_list = [
        query.search_query if isinstance(query, SearchQuery) else str(query)
        for query in results.queries
    ]

    # 웹 검색 실행 후 결과 대기
    search_docs = await run_search_queries(
        query_list,
        num_results=4,
        include_raw_content=False
    )

    if not search_docs:
        print("Warning: No search results returned")
        search_context = "No search results available."
    else:
        search_context = format_search_query_results(
            search_docs,
            include_raw_content=False
        )

    # 섹션 생성
    lang_instr = LANGUAGE_INSTRUCTION.get(language, "")
    system_instructions_sections = REPORT_PLAN_SECTION_GENERATOR_PROMPT.format(
        topic=topic,
        report_organization=report_structure,
        search_context=search_context
    ) + lang_instr

    structured_llm = llm.with_structured_output(Sections)
    report_sections = await structured_llm.ainvoke([
        SystemMessage(content=system_instructions_sections),
        HumanMessage(content="Generate the sections of the report. Your response must include a 'sections' field containing a list of sections. Each section must have: name, description, plan, research, and content fields.")
    ])

    print('--- Generating Report Plan Completed ---')
    return {"sections": report_sections.sections}


# 섹션 빌더 에이전트

async def generate_queries(state: SectionState):
    """특정 보고서 섹션에 대한 검색 쿼리를 생성한다."""

    section = state["section"]
    model_name = state.get("model_name", "gpt-5-nano")
    print('--- Generating Search Queries for Section: '+ section.name +' ---')

    try:
        llm = get_llm(model_name)
    except Exception as e:
        print(f"Error initializing OpenAI API: {e}")
        return {"search_queries": []}

    structured_llm = llm.with_structured_output(Queries)
    system_instructions = REPORT_SECTION_QUERY_GENERATOR_PROMPT.format(
        section_topic=section.description, number_of_queries=3
    )
    search_queries = await structured_llm.ainvoke([
        SystemMessage(content=system_instructions),
        HumanMessage(content="Generate search queries on the provided topic."),
    ])

    print('--- Generating Search Queries for Section: '+ section.name +' Completed ---')

    return {"search_queries": search_queries.queries}

# 섹션 빌더 웹 검색

async def search_web(state: SectionState):
    """각 쿼리로 웹을 검색하고 원본 소스 목록과 포맷된 소스 문자열을 반환한다."""

    search_queries = state["search_queries"]
    print('--- Searching Web for Queries ---')

    # 웹 검색
    query_list = [query.search_query for query in search_queries]
    search_docs = await run_search_queries(query_list, num_results=2, include_raw_content=True)

    # 중복 제거 및 소스 포맷팅
    search_context = format_search_query_results(search_docs, max_tokens=400, include_raw_content=True)

    print('--- Searching Web for Queries Completed ---')

    return {"source_str": search_context}

# 섹션 빌더 작성기

async def write_section(state: SectionState):
    """보고서의 특정 섹션을 작성한다."""

    section = state["section"]
    source_str = state["source_str"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    print('--- Writing Section : '+ section.name +' ---')

    try:
        llm = get_llm(model_name)
    except Exception as e:
        print(f"Error initializing OpenAI API: {e}")
        section.content = "Error: Could not generate content due to API issues."
        return {"completed_sections": [section]}

    lang_instr = LANGUAGE_INSTRUCTION.get(language, "")
    system_instructions = SECTION_WRITER_PROMPT.format(
        section_title=section.name, section_topic=section.description, context=source_str
    ) + lang_instr

    try:
        section_content = await llm.ainvoke([
            SystemMessage(content=system_instructions),
            HumanMessage(content="Generate a report section based on the provided sources."),
        ])
    except Exception as e:
        print(f"Error writing section '{section.name}': {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."
        return {"completed_sections": [section]}

    section.content = section_content.content
    print('--- Writing Section : '+ section.name +' Completed ---')
    return {"completed_sections": [section]}

# 섹션 빌더 서브 에이전트

# 노드 및 엣지 추가
section_builder = StateGraph(SectionState, output_schema=SectionOutputState)
section_builder.add_node("generate_queries", generate_queries)
section_builder.add_node("search_web", search_web)
section_builder.add_node("write_section", write_section)

section_builder.add_edge(START, "generate_queries")
section_builder.add_edge("generate_queries", "search_web")
section_builder.add_edge("search_web", "write_section")
section_builder.add_edge("write_section", END)
section_builder_subagent = section_builder.compile()

# 섹션 병렬 작성

def parallelize_section_writing(state: ReportState):
    """웹 리서치가 필요한 섹션들을 병렬로 작성하는 map 단계."""

    # 리서치가 필요한 섹션에 대해 Send() API로 병렬 작성 시작
    return [
        Send("section_builder_with_web_search",
             {"section": s,
              "language": state.get("language", "English"),
              "model_name": state.get("model_name", "gpt-5")})
            for s in state["sections"]
              if s.research
    ]

# 섹션 빌더 포맷팅

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

    print('--- Formatting Completed Sections ---')

    # 완료된 섹션 목록
    completed_sections = state["completed_sections"]

    # 최종 섹션 컨텍스트로 사용하기 위해 완료된 섹션을 문자열로 포맷
    completed_report_sections = format_sections(completed_sections)

    print('--- Formatting Completed Sections is Done ---')

    return {"report_sections_from_research": completed_report_sections}


# 최종 섹션

async def write_final_sections(state: SectionState):
    """웹 검색 없이 완료된 섹션을 컨텍스트로 활용해 최종 섹션을 작성한다."""

    section = state["section"]
    completed_report_sections = state["report_sections_from_research"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    print('--- Writing Final Section: '+ section.name + ' ---')

    try:
        llm = get_llm(model_name)
    except Exception as e:
        print(f"Error initializing OpenAI API: {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."
        return {"completed_sections": [section]}

    lang_instr = LANGUAGE_INSTRUCTION.get(language, "")
    system_instructions = FINAL_SECTION_WRITER_PROMPT.format(
        section_title=section.name, section_topic=section.description, context=completed_report_sections
    ) + lang_instr

    try:
        section_content = await llm.ainvoke([
            SystemMessage(content=system_instructions),
            HumanMessage(content="Craft a report section based on the provided sources."),
        ])
    except Exception as e:
        print(f"Error writing final section '{section.name}': {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."
        return {"completed_sections": [section]}

    section.content = section_content.content
    print('--- Writing Final Section: '+ section.name + ' Completed ---')
    return {"completed_sections": [section]}

# 최종 섹션 병렬 작성

def parallelize_final_section_writing(state: ReportState):
    """Send API를 사용해 최종 섹션들을 병렬로 작성한다."""

    # 리서치가 불필요한 섹션에 대해 Send() API로 병렬 작성 시작
    return [
        Send("write_final_sections",
             {"section": s,
              "report_sections_from_research": state["report_sections_from_research"],
              "language": state.get("language", "English"),
              "model_name": state.get("model_name", "gpt-4o")})
                 for s in state["sections"]
                    if not s.research
    ]

# 최종 보고서 컴파일

def compile_final_report(state: ReportState):
    """최종 보고서를 컴파일한다."""

    # 섹션 가져오기
    sections = state["sections"]
    completed_sections = {s.name: s.content for s in state["completed_sections"]}

    print('--- Compiling Final Report ---')

    # 원래 순서를 유지하며 완료된 내용으로 섹션 업데이트
    for section in sections:
        section.content = completed_sections[section.name]

    # 최종 보고서 컴파일
    all_sections = "\n\n".join([s.content for s in sections])
    # Markdown에서 $ 기호가 올바르게 표시되도록 이스케이프 처리
    formatted_sections = all_sections.replace("\\$", "TEMP_PLACEHOLDER")  # 이미 이스케이프된 $ 임시 표시
    formatted_sections = formatted_sections.replace("$", "\\$")  # 모든 $ 이스케이프
    formatted_sections = formatted_sections.replace("TEMP_PLACEHOLDER", "\\$")  # 원래 이스케이프된 $ 복원

# 이 시점에서 formatted_sections는 올바르게 이스케이프된 Markdown 텍스트를 포함한다


    print('--- Compiling Final Report Done ---')

    return {"final_report": formatted_sections}

# 최종 보고서 작성 플래닝 및 작성 에이전트

builder = StateGraph(ReportState, input_schema=ReportStateInput, output_schema=ReportStateOutput)

builder.add_node("generate_report_plan", generate_report_plan)
builder.add_node("section_builder_with_web_search", section_builder_subagent)
builder.add_node("format_completed_sections", format_completed_sections)
builder.add_node("write_final_sections", write_final_sections)
builder.add_node("compile_final_report", compile_final_report)

builder.add_edge(START, "generate_report_plan")
builder.add_conditional_edges("generate_report_plan",
                              parallelize_section_writing,
                              ["section_builder_with_web_search"])
builder.add_edge("section_builder_with_web_search", "format_completed_sections")
builder.add_conditional_edges("format_completed_sections",
                              parallelize_final_section_writing,
                              ["write_final_sections"])
builder.add_edge("write_final_sections", "compile_final_report")
builder.add_edge("compile_final_report", END)

# 체크포인터 설정:
# - DATABASE_URL이 MySQL이면 → langgraph-checkpoint-mysql (AsyncMySQLSaver)
# - 그 외(SQLite 등)면 → 로컬 checkpoints.db (AsyncSqliteSaver)
# FastAPI lifespan에서 init_checkpointer()를 호출해 초기화함.
import os as _os
import re as _re
from urllib.parse import urlparse as _urlparse

_ckpt_conn = None
reporter_agent = None  # lifespan에서 초기화됨


def _parse_mysql_url(url: str) -> dict:
    """mysql+pymysql://user:pass@host:port/db 형태의 URL을 파싱해 dict로 반환."""
    # aiomysql은 'mysql://' 형태를 사용하므로 드라이버 접두사 제거
    clean = _re.sub(r'^mysql\+[^:]+://', 'mysql://', url)
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
        # ── MySQL 체크포인터 ──────────────────────────────────────────
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
        await checkpointer.setup()   # 체크포인트 테이블 자동 생성

        # MySQL 8.0 기본 collation(utf8mb4_0900_ai_ci)과 기존 테이블 collation 불일치 방지
        # 테이블을 연결 기본값에 맞게 일괄 변환
        _checkpoint_tables = [
            "checkpoint_migrations",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
        ]
        async with _ckpt_conn.cursor() as _cur:
            for _tbl in _checkpoint_tables:
                await _cur.execute(
                    f"ALTER TABLE `{_tbl}` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
    else:
        # ── SQLite 체크포인터 (로컬/테스트용 fallback) ────────────────
        import json as _json
        from pydantic import BaseModel as _BaseModel
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.checkpoint.sqlite.aio import get_checkpoint_metadata as _get_checkpoint_metadata
        import aiosqlite

        class _PydanticEncoder(_json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, _BaseModel):
                    return obj.model_dump()
                return super().default(obj)

        class _PydanticAwareSqliteSaver(AsyncSqliteSaver):
            async def aput(self, config, checkpoint, metadata, _new_versions):
                await self.setup()
                thread_id = config["configurable"]["thread_id"]
                checkpoint_ns = config["configurable"]["checkpoint_ns"]
                type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
                serialized_metadata = _json.dumps(
                    _get_checkpoint_metadata(config, metadata),
                    ensure_ascii=False,
                    cls=_PydanticEncoder,
                ).encode("utf-8", "ignore")
                async with (
                    self.lock,
                    self.conn.execute(
                        "INSERT OR REPLACE INTO checkpoints "
                        "(thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(thread_id),
                            checkpoint_ns,
                            checkpoint["id"],
                            config["configurable"].get("checkpoint_id"),
                            type_,
                            serialized_checkpoint,
                            serialized_metadata,
                        ),
                    ),
                ):
                    await self.conn.commit()
                return {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint["id"],
                    }
                }

        _ckpt_path = _os.path.abspath(
            _os.path.join(_os.path.dirname(__file__), "..", "checkpoints.db")
        )
        _ckpt_conn = await aiosqlite.connect(_ckpt_path)
        checkpointer = _PydanticAwareSqliteSaver(_ckpt_conn)

    reporter_agent = builder.compile(
        checkpointer=checkpointer,
        interrupt_after=["generate_report_plan"],
    )


async def close_checkpointer():
    """앱 종료 시 DB 연결을 닫는다."""
    global _ckpt_conn
    if _ckpt_conn:
        try:
            await _ckpt_conn.ensure_closed() if hasattr(_ckpt_conn, 'ensure_closed') else await _ckpt_conn.close()
        except Exception:
            pass
        _ckpt_conn = None