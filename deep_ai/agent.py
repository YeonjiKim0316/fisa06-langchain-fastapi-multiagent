from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from deep_ai.prompts import REPORT_PLAN_QUERY_GENERATOR_PROMPT, REPORT_PLAN_SECTION_GENERATOR_PROMPT, SECTION_WRITER_PROMPT, FINAL_SECTION_WRITER_PROMPT, REPORT_SECTION_QUERY_GENERATOR_PROMPT, DEFAULT_REPORT_STRUCTURE, LANGUAGE_INSTRUCTION
from deep_ai.util import format_search_query_results, run_search_queries

from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send

from typing_extensions import TypedDict
from pydantic import BaseModel, Field
import operator
from typing import Annotated, List, Optional, Literal


# print("The keys are loaded")

class Section(BaseModel):
    name: str = Field(
        description="Name for a particular section of the report.",
    )
    description: str = Field(
        description="Brief overview of the main topics and concepts to be covered in this section.",
    )
    research: bool = Field(
        description="Whether to perform web search for this section of the report."
    )
    content: str = Field(
        description="The content for this section."
    )

class Sections(BaseModel):
    sections: List[Section] = Field(
        description="All the Sections of the overall report.",
    )

class SearchQuery(BaseModel):
    search_query: str = Field(None, description="Query for web search.")

class Queries(BaseModel):
    queries: List[SearchQuery] = Field(
        description="List of web search queries.",
    )

class ReportStateInput(TypedDict):
    topic: str # Report topic
    language: str # Output language: "한국어" or "English"
    model_name: str # LLM model: "gpt-5" or "gpt-5-nano"

class ReportStateOutput(TypedDict):
    final_report: str # Final report

class ReportState(TypedDict):
    topic: str # Report topic
    language: str # Output language
    model_name: str # LLM model
    sections: list[Section] # List of report sections
    completed_sections: Annotated[list, operator.add] # Send() API
    report_sections_from_research: str # String of any completed sections from research to write final sections
    final_report: str # Final report

class SectionState(TypedDict):
    section: Section # Report section
    search_queries: list[SearchQuery] # List of search queries
    source_str: str # String of formatted source content from web search
    report_sections_from_research: str # String of any completed sections from research to write final sections
    completed_sections: list[Section] # Final key we duplicate in outer state for Send() API
    language: str # Output language
    model_name: str # LLM model

class SectionOutputState(TypedDict):
    completed_sections: list[Section] # Final key we duplicate in outer state for Send() API

# Instead of loading the LLM at import time, create a function to get it on demand
def get_llm(model_name="gpt-4o-mini"):
    """Get the LLM model, initializing it on demand with name mapping."""
    import os
    # Custom mapping for future-proof naming
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

# Report Planner agent
async def generate_report_plan(state: ReportState):
    """Generate the overall plan for building the report"""
    topic = state["topic"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    openai_api_key = state.get("openai_api_key")
    print('--- Generating Report Plan ---')

    # Get LLM on demand
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

    # Generate queries
    results = await structured_llm.ainvoke([
        SystemMessage(content=system_instructions_query),
        HumanMessage(content='Generate search queries that will help with planning the sections of the report.')
    ])

    # Convert SearchQuery objects to strings
    query_list = [
        query.search_query if isinstance(query, SearchQuery) else str(query)
        for query in results.queries
    ]

    # Search web and ensure we wait for results
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

    # Generate sections
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
    
    
# Section Builder agent

def generate_queries(state: SectionState):
    """ Generate search queries for a specific report section """

    # Get state
    section = state["section"]
    model_name = state.get("model_name", "gpt-5-nano")
    openai_api_key = state.get("openai_api_key")
    print('--- Generating Search Queries for Section: '+ section.name +' ---')

    # Get LLM on demand
    try:
        llm = get_llm(model_name)
    except Exception as e:
        print(f"Error initializing OpenAI API: {e}")
        return {"search_queries": []}

    # Get configuration
    number_of_queries = 3

    # Generate queries
    structured_llm = llm.with_structured_output(Queries)

    # Format system instructions
    system_instructions = REPORT_SECTION_QUERY_GENERATOR_PROMPT.format(section_topic=section.description,
                                                                       number_of_queries=number_of_queries)

    # Generate queries
    user_instruction = "Generate search queries on the provided topic."
    search_queries = structured_llm.invoke([SystemMessage(content=system_instructions),
                                     HumanMessage(content=user_instruction)])

    print('--- Generating Search Queries for Section: '+ section.name +' Completed ---')

    return {"search_queries": search_queries.queries}

# Section Builder Web Search

async def search_web(state: SectionState):
    """ Search the web for each query, then return a list of raw sources and a formatted string of sources."""

    # Get state
    search_queries = state["search_queries"]
    tavily_api_key = state.get("tavily_api_key")

    print('--- Searching Web for Queries ---')

    # Web search
    query_list = [query.search_query for query in search_queries]
    search_docs = await run_search_queries(query_list, num_results=2, include_raw_content=True)

    # Deduplicate and format sources
    search_context = format_search_query_results(search_docs, max_tokens=400, include_raw_content=True)

    print('--- Searching Web for Queries Completed ---')

    return {"source_str": search_context}

# Section Builder Writer

def write_section(state: SectionState):
    """ Write a section of the report """

    # Get state
    section = state["section"]
    source_str = state["source_str"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    openai_api_key = state.get("openai_api_key")

    print('--- Writing Section : '+ section.name +' ---')

    # Get LLM on demand
    try:
        llm = get_llm(model_name)
    except Exception as e:
        print(f"Error initializing OpenAI API: {e}")
        section.content = "Error: Could not generate content due to API issues."
        return {"completed_sections": [section]}

    # Format system instructions
    lang_instr = LANGUAGE_INSTRUCTION.get(language, "")
    system_instructions = SECTION_WRITER_PROMPT.format(section_title=section.name,
                                                       section_topic=section.description,
                                                       context=source_str) + lang_instr

    # Generate section
    user_instruction = "Generate a report section based on the provided sources."
    try:
        section_content = llm.invoke([SystemMessage(content=system_instructions),
                                      HumanMessage(content=user_instruction)])
    except Exception as e:
        print(f"Error writing section '{section.name}': {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."
        return {"completed_sections": [section]}

    # Write content to the section object
    section.content = section_content.content

    print('--- Writing Section : '+ section.name +' Completed ---')

    # Write the updated section to completed sections
    return {"completed_sections": [section]}

# Section Builder Sub Agent

# Add nodes and edges
section_builder = StateGraph(SectionState, output=SectionOutputState)
section_builder.add_node("generate_queries", generate_queries)
section_builder.add_node("search_web", search_web)
section_builder.add_node("write_section", write_section)

section_builder.add_edge(START, "generate_queries")
section_builder.add_edge("generate_queries", "search_web")
section_builder.add_edge("search_web", "write_section")
section_builder.add_edge("write_section", END)
section_builder_subagent = section_builder.compile()

# Parallelize Section Writing

def parallelize_section_writing(state: ReportState):
    """ This is the "map" step when we kick off web research for some sections of the report in parallel and then write the section"""

    # Kick off section writing in parallel via Send() API for any sections that require research
    return [
        Send("section_builder_with_web_search",
             {"section": s,
              "language": state.get("language", "English"),
              "model_name": state.get("model_name", "gpt-5")})
            for s in state["sections"]
              if s.research
    ]
    
# Section Builder Format Sections

def format_sections(sections: list[Section]) -> str:
    """ Format a list of report sections into a single text string """
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
    """ Gather completed sections from research and format them as context for writing the final sections """

    print('--- Formatting Completed Sections ---')

    # List of completed sections
    completed_sections = state["completed_sections"]

    # Format completed section to str to use as context for final sections
    completed_report_sections = format_sections(completed_sections)

    print('--- Formatting Completed Sections is Done ---')

    return {"report_sections_from_research": completed_report_sections}


# Final Section

def write_final_sections(state: SectionState):
    """ Write the final sections of the report, which do not require web search and use the completed sections as context"""

    # Get state
    section = state["section"]
    completed_report_sections = state["report_sections_from_research"]
    language = state.get("language", "English")
    model_name = state.get("model_name", "gpt-5-nano")
    openai_api_key = state.get("openai_api_key")

    print('--- Writing Final Section: '+ section.name + ' ---')

    # Get LLM on demand
    try:
        llm = get_llm(model_name)
    except Exception as e:
        print(f"Error initializing OpenAI API: {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."
        return {"completed_sections": [section]}

    # Format system instructions
    lang_instr = LANGUAGE_INSTRUCTION.get(language, "")
    system_instructions = FINAL_SECTION_WRITER_PROMPT.format(section_title=section.name,
                                                             section_topic=section.description,
                                                             context=completed_report_sections) + lang_instr

    # Generate section
    user_instruction = "Craft a report section based on the provided sources."
    try:
        section_content = llm.invoke([SystemMessage(content=system_instructions),
                                      HumanMessage(content=user_instruction)])
    except Exception as e:
        print(f"Error writing final section '{section.name}': {e}")
        section.content = f"## {section.name}\n\nContent could not be generated due to an API error."
        return {"completed_sections": [section]}

    # Write content to section
    section.content = section_content.content

    print('--- Writing Final Section: '+ section.name + ' Completed ---')

    # Write the updated section to completed sections
    return {"completed_sections": [section]}

# Final Section Writing Parallelization

def parallelize_final_section_writing(state: ReportState):
    """ Write any final sections using the Send API to parallelize the process """

    # Kick off section writing in parallel via Send() API for any sections that do not require research
    return [
        Send("write_final_sections",
             {"section": s,
              "report_sections_from_research": state["report_sections_from_research"],
              "language": state.get("language", "English"),
              "model_name": state.get("model_name", "gpt-4o")})
                 for s in state["sections"]
                    if not s.research
    ]
    
# Compile the final report

def compile_final_report(state: ReportState):
    """ Compile the final report """

    # Get sections
    sections = state["sections"]
    completed_sections = {s.name: s.content for s in state["completed_sections"]}

    print('--- Compiling Final Report ---')

    # Update sections with completed content while maintaining original order
    for section in sections:
        section.content = completed_sections[section.name]

    # Compile final report
    all_sections = "\n\n".join([s.content for s in sections])
    # Escape unescaped $ symbols to display properly in Markdown
    formatted_sections = all_sections.replace("\\$", "TEMP_PLACEHOLDER")  # Temporarily mark already escaped $
    formatted_sections = formatted_sections.replace("$", "\\$")  # Escape all $
    formatted_sections = formatted_sections.replace("TEMP_PLACEHOLDER", "\\$")  # Restore originally escaped $

# Now escaped_sections contains the properly escaped Markdown text


    print('--- Compiling Final Report Done ---')

    return {"final_report": formatted_sections}

# Final Report Writer Planning and Writing Agent

builder = StateGraph(ReportState, input=ReportStateInput, output=ReportStateOutput)

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
        from langgraph.checkpoint.mysql.aio import AsyncMySQLSaver

        conn_params = _parse_mysql_url(db_url)
        _ckpt_conn = await aiomysql.connect(
            host=conn_params["host"],
            port=conn_params["port"],
            user=conn_params["user"],
            password=conn_params["password"],
            db=conn_params["db"],
            autocommit=True,
        )
        checkpointer = AsyncMySQLSaver(_ckpt_conn)
        await checkpointer.setup()   # 체크포인트 테이블 자동 생성
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
            async def aput(self, config, checkpoint, metadata, new_versions):
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

# Run

async def call_planner_agent(agent, prompt, config={"recursion_limit": 50}, verbose=False):
    events = agent.astream(
        {'topic' : prompt},
        config,
        stream_mode="values",
    )

    async for event in events:
        for k, v in event.items():
            if verbose:
                if k != "__end__":
                    print(repr(k) + ' -> ' + repr(v))
            if k == 'final_report':
                print('='*50)
                print('Final Report:')
                print('='*50)
                # Simply print the report content directly
                print(v)
                print('='*50)

# Create a main async function
async def main():
    # Get topic from user
    topic = str(input("Enter the topic of the report: "))
    await call_planner_agent(agent=reporter_agent, prompt=topic)

# Run the async function with asyncio
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())