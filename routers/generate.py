import os
import json
import logging
import asyncio
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from core.dependencies import require_user
from core.session import get_session
from services.storage_service import save_report

router = APIRouter(tags=["generate"])
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("deepresearch.generate")


@router.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request, user=Depends(require_user)):
    session = get_session(request)
    from core.config import get_settings
    settings = get_settings()
    # 세션 키 또는 설정 파일 키 중 하나라도 있으면 OK
    has_keys = bool(
        (session.get("openai_api_key") or settings.openai_api_key)
        and (session.get("tavily_api_key") or settings.tavily_api_key)
    )
    return templates.TemplateResponse("generate.html", {
        "request": request,
        "user": user,
        "session": session,
        "need_api_keys": not has_keys,
        "messages": [],
    })


@router.get("/generate/stream")
async def stream_report(
    request: Request,
    topic: str,
    thread_id: str = None,
    model_name: str = None,
    excluded: str = None,
    user=Depends(require_user),
):
    """SSE 엔드포인트: LangGraph 진행 이벤트를 스트리밍한다. 계획 승인을 위한 HITL 중단을 지원한다."""
    session = get_session(request)

    # 기존 thread_id 사용 또는 새 리서치를 위한 신규 생성
    import uuid
    is_resume = True
    if not thread_id:
        thread_id = str(uuid.uuid4())
        is_resume = False

    from core.config import get_settings
    settings = get_settings()

    # 세션 키 우선, 설정 파일 → os.environ 순으로 폴백
    openai_key = session.get("openai_api_key") or settings.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    tavily_key = session.get("tavily_api_key") or settings.tavily_api_key or os.environ.get("TAVILY_API_KEY", "")

    language = session.get("language", "한국어")
    model_name = model_name or session.get("model_name", "gpt-5-nano")

    # LangGraph 에이전트가 os.environ에서 키를 읽으므로 주입
    # (단일 사용자 범위에서만 유효 — 멀티유저 동시 실행 시 키 충돌 가능)
    if openai_key:
        os.environ["OPENAI_API_KEY"] = openai_key
    if tavily_key:
        os.environ["TAVILY_API_KEY"] = tavily_key

    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("TAVILY_API_KEY"):
        async def err_gen():
            yield {"event": "stream_error", "data": json.dumps({"message": "API 키가 설정되지 않았습니다. 대시보드에서 설정해주세요."})}
        return EventSourceResponse(err_gen())

    async def event_generator():
        step_labels = {
            "generate_report_plan": "📋 보고서 구조 계획 중...",
            "section_builder_with_web_search": "🔍 섹션 리서치 및 작성 중...",
            "format_completed_sections": "📝 섹션 정리 중...",
            "write_final_sections": "✍️ 서론/결론 작성 중...",
            "compile_final_report": "📦 최종 보고서 컴파일 중...",
        }
        total_steps = len(step_labels)
        step_count = 0
        final_report = None
        captured_sections = []
        last_snapshot = {}
        research_logs = []

        # 브라우저가 연결 끊김으로 처리하지 않도록 즉시 이벤트 전송
        yield {
            "event": "progress",
            "data": json.dumps({
                "step": "initializing",
                "label": "📡 리서치 준비 중...",
                "progress": 0.05,
            }),
        }
        await asyncio.sleep(0.1)

        try:
            import deep_ai.agent as _agent_module
            reporter_agent = _agent_module.reporter_agent
            if reporter_agent is None:
                raise RuntimeError("체크포인터가 초기화되지 않았습니다. 서버를 재시작해주세요.")

            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

            # 재개 시 제외된 섹션으로 상태 업데이트
            if is_resume and excluded:
                state = await reporter_agent.aget_state(config)
                current_sections = state.values.get("sections", [])
                excluded_indices = [int(i.strip()) for i in excluded.split(",") if i.strip().isdigit()]
                if excluded_indices and current_sections:
                    filtered_sections = [s for i, s in enumerate(current_sections) if i not in excluded_indices]
                    await reporter_agent.aupdate_state(config, {"sections": filtered_sections})

            # 에이전트 입력 구성 (재개 시 None으로 LangGraph가 체크포인트에서 계속)
            agent_input = None
            if not is_resume:
                agent_input = {
                    "topic": topic,
                    "language": language,
                    "model_name": model_name,
                }

            # ── 핵심 수정 ────────────────────────────────────────────────────────
            # Queue + 백그라운드 Task를 사용해 LangGraph 코루틴이 절대 취소되지 않도록 함.
            # 이전 방식(asyncio.wait_for(__anext__, timeout))은 타임아웃 시 코루틴을 취소해
            # MemorySaver가 체크포인트를 기록하지 못함 → 인터럽트 후 섹션이 비어 있는 버그 발생.
            # ────────────────────────────────────────────────────────────────────
            q: asyncio.Queue = asyncio.Queue()

            async def _run_agent_stream():
                try:
                    async for snap in reporter_agent.astream(agent_input, config, stream_mode="values"):
                        await q.put(("snapshot", snap))
                    await q.put(("done", None))
                except Exception as exc:
                    await q.put(("error", exc))

            agent_task = asyncio.create_task(_run_agent_stream())

            while True:
                if await request.is_disconnected():
                    logger.info("Client disconnected, stopping stream")
                    agent_task.cancel()
                    break

                try:
                    msg_type, payload = await asyncio.wait_for(q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # 5초마다 하트비트 전송 — LangGraph 태스크는 안전하게 계속 실행 중
                    progress = min(max((step_count + 0.5) / max(total_steps, 1), 0.05), 0.95)
                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "step": "working",
                            "label": "🧠 AI가 계속해서 분석 및 리서치를 진행 중입니다... (1~2분 소요)",
                            "progress": round(progress, 2),
                        }),
                    }
                    continue

                if msg_type == "done":
                    break
                elif msg_type == "error":
                    raise payload

                # msg_type == "snapshot"
                state_snapshot = payload
                last_snapshot = state_snapshot  # 항상 최신 상태 추적

                # final_report가 있으면 항상 캡처
                if state_snapshot.get("final_report"):
                    final_report = state_snapshot["final_report"]

                # 상태 변화를 통해 완료된 노드 감지
                # 재개 시 첫 스냅샷에는 기존 상태가 있으므로 오인식 방지
                node_name = None
                if not is_resume and state_snapshot.get("sections") and not captured_sections:
                    # Initial run: generate_report_plan just finished
                    node_name = "generate_report_plan"
                    captured_sections = state_snapshot["sections"]
                elif state_snapshot.get("completed_sections"):
                    node_name = "section_builder_with_web_search"
                elif state_snapshot.get("report_sections_from_research") and not state_snapshot.get("final_report"):
                    node_name = "format_completed_sections"
                elif state_snapshot.get("final_report"):
                    node_name = "compile_final_report"

                # 완료된 각 섹션의 내용을 UI에 점진적으로 스트리밍
                if state_snapshot.get("completed_sections"):
                    for section in state_snapshot["completed_sections"]:
                        if hasattr(section, "content") and section.content:
                            already_sent = any(
                                l.get("title") == section.name
                                for l in research_logs
                                if l.get("type") == "content"
                            )
                            if not already_sent:
                                log_entry = {"type": "content", "title": section.name, "body": section.content}
                                research_logs.append(log_entry)
                                yield {
                                    "event": "content",
                                    "data": json.dumps({"name": section.name, "content": section.content}),
                                }

                if node_name:
                    step_count += 1
                    progress = min(step_count / max(total_steps, 1), 0.95)
                    label = step_labels.get(node_name, f"⚙️ {node_name} 처리 중...")
                    research_logs.append({"type": "progress", "label": label})
                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "step": node_name,
                            "label": label,
                            "progress": round(progress, 2),
                        }),
                    }
                    await asyncio.sleep(0)

            # 스트림 종료 후 → HITL 인터럽트 확인
            next_state = await reporter_agent.aget_state(config)
            if next_state.next:
                # captured_sections는 스트림에서 캡처; 비어 있으면 aget_state로 폴백
                sections = captured_sections or next_state.values.get("sections", [])
                sections_data = [
                    {"name": s.name, "description": s.description, "research": s.research}
                    for s in sections
                ]
                yield {
                    "event": "plan_generated",
                    "data": json.dumps({
                        "thread_id": thread_id,
                        "sections": sections_data,
                        "label": "✅ 리서치 계획이 수립되었습니다. 내용을 확인하고 승인해주세요."
                    }),
                }
                await asyncio.sleep(1)
                return

            if final_report:
                try:
                    save_report(str(user.id), topic, final_report, logs=research_logs)
                except Exception as save_err:
                    logger.warning(f"Auto-save failed: {save_err}")

                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "report": final_report,
                        "topic": topic,
                        "progress": 1.0,
                    }),
                }
            else:
                yield {
                    "event": "stream_error",
                    "data": json.dumps({"message": "보고서 생성에 실패했습니다."}),
                }

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Stream error: {tb}")
            try:
                with open("error_dump.txt", "w", encoding="utf-8") as f:
                    f.write(tb)
            except Exception:
                pass
            yield {
                "event": "stream_error",
                "data": json.dumps({"message": f"오류가 발생했습니다: {str(e)}"}),
            }

    return EventSourceResponse(event_generator())
