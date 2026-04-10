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
logger = logging.getLogger("fisaai6-multi-agent.generate")


@router.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request, user=Depends(require_user)):
    session = get_session(request)
    from core.config import get_settings
    settings = get_settings()
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

    import uuid
    is_resume = True
    if not thread_id:
        thread_id = str(uuid.uuid4())
        is_resume = False

    from core.config import get_settings
    settings = get_settings()

    # 세션 키 우선, 설정 파일 → 환경변수 순으로 폴백
    openai_key = session.get("openai_api_key") or settings.openai_api_key or ""
    tavily_key = session.get("tavily_api_key") or settings.tavily_api_key or ""

    if not openai_key or not tavily_key:
        async def err_gen():
            yield {
                "event": "stream_error",
                "data": json.dumps({"message": "API 키가 설정되지 않았습니다. 대시보드에서 설정해주세요."}),
            }
        return EventSourceResponse(err_gen())

    language = session.get("language", "한국어")
    model_name = model_name or session.get("model_name", "gpt-5-nano")

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
        research_logs = []

        yield {
            "event": "progress",
            "data": json.dumps({"step": "initializing", "label": "📡 리서치 준비 중...", "progress": 0.05}),
        }
        await asyncio.sleep(0.1)

        try:
            import deep_ai.agent as _agent_module
            reporter_agent = _agent_module.reporter_agent
            if reporter_agent is None:
                raise RuntimeError("체크포인터가 초기화되지 않았습니다. 서버를 재시작해주세요.")

            # ⚠️ API 키를 configurable에서 제거 (checkpoint에 저장되는 것을 방지)
            # 대신 os.environ에 임시로 설정 → 노드 함수에서 os.environ.get() 사용
            import os
            old_openai_key = os.environ.get("OPENAI_API_KEY")
            old_tavily_key = os.environ.get("TAVILY_API_KEY")
            os.environ["OPENAI_API_KEY"] = openai_key
            os.environ["TAVILY_API_KEY"] = tavily_key

            config = {
                "configurable": {
                    "thread_id": thread_id,
                },
                "recursion_limit": 50,
            }

            # 재개 시 제외된 섹션으로 상태 업데이트
            if is_resume and excluded:
                state = await reporter_agent.aget_state(config)
                current_sections = state.values.get("sections", [])
                excluded_indices = [int(i.strip()) for i in excluded.split(",") if i.strip().isdigit()]
                if excluded_indices and current_sections:
                    filtered = [s for i, s in enumerate(current_sections) if i not in excluded_indices]
                    await reporter_agent.aupdate_state(config, {"sections": filtered})

            agent_input = None if is_resume else {
                "topic": topic,
                "language": language,
                "model_name": model_name,
            }

            # ── Queue + 백그라운드 Task ────────────────────────────────────────
            # astream 코루틴을 별도 Task로 실행해 타임아웃 시 취소하지 않음.
            # 타임아웃 시에도 하트비트만 전송하고 Task는 계속 실행.
            q: asyncio.Queue = asyncio.Queue()

            async def _run_agent_stream():
                try:
                    # stream_mode="updates": 각 항목이 {node_name: state_delta} 형태
                    # → 노드 이름을 직접 얻으므로 상태 필드 추론 불필요
                    async for updates in reporter_agent.astream(
                        agent_input, config, stream_mode="updates"
                    ):
                        await q.put(("update", updates))
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

                # msg_type == "update": {node_name: state_delta} 또는 {"__interrupt__": [...]}
                updates: dict = payload

                for node_name, state_delta in updates.items():
                    if not isinstance(state_delta, dict):
                        continue

                    # 완료된 섹션 내용을 UI에 점진적으로 스트리밍
                    for section in state_delta.get("completed_sections", []):
                        if hasattr(section, "content") and section.content:
                            log_entry = {"type": "content", "title": section.name, "body": section.content}
                            research_logs.append(log_entry)
                            yield {
                                "event": "content",
                                "data": json.dumps({"name": section.name, "content": section.content}),
                            }

                    # 최종 보고서 캡처
                    if "final_report" in state_delta:
                        final_report = state_delta["final_report"]

                    # 알려진 노드에 대해서만 진행률 이벤트 발행
                    if node_name in step_labels:
                        step_count += 1
                        progress = min(step_count / max(total_steps, 1), 0.95)
                        label = step_labels[node_name]
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

            # ── 스트림 종료 후: HITL 인터럽트 확인 ───────────────────────────
            next_state = await reporter_agent.aget_state(config)
            if next_state.next:
                sections = next_state.values.get("sections", [])
                sections_data = [
                    {"name": s.name, "description": s.description, "research": s.research}
                    for s in sections
                ]
                yield {
                    "event": "plan_generated",
                    "data": json.dumps({
                        "thread_id": thread_id,
                        "sections": sections_data,
                        "label": "✅ 리서치 계획이 수립되었습니다. 내용을 확인하고 승인해주세요.",
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
        finally:
            # 환경 변수 복원
            if old_openai_key is not None:
                os.environ["OPENAI_API_KEY"] = old_openai_key
            else:
                os.environ.pop("OPENAI_API_KEY", None)
            if old_tavily_key is not None:
                os.environ["TAVILY_API_KEY"] = old_tavily_key
            else:
                os.environ.pop("TAVILY_API_KEY", None)

    return EventSourceResponse(event_generator())
