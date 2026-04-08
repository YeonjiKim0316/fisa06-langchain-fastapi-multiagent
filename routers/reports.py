import logging
from urllib.parse import quote
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from core.dependencies import require_user
from core.session import get_session, update_session
from core.utils import flash, topic_from_filename
from services.storage_service import load_saved_reports, get_report_content, delete_report

router = APIRouter(tags=["reports"])
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("deepresearch.reports")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(require_user)):
    session = get_session(request)
    reports = load_saved_reports(str(user.id))
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "reports": reports,
        "session": session,
        "messages": [],
    })


@router.post("/settings/apikeys")
async def save_api_keys(
    request: Request,
    openai_key: str = Form(...),
    tavily_key: str = Form(...),
    user=Depends(require_user),
):
    response = RedirectResponse(url="/generate", status_code=302)
    update_session(request, response, {
        "openai_api_key": openai_key,
        "tavily_api_key": tavily_key,
        "api_keys_set": True,
    })
    return flash(response, "success", "API 키가 저장되었습니다!")


@router.post("/settings/preferences")
async def save_preferences(
    request: Request,
    language: str = Form("한국어"),
    model_name: str = Form("gpt-5-nano"),
    user=Depends(require_user),
):
    response = RedirectResponse(url="/dashboard", status_code=302)
    update_session(request, response, {
        "language": language,
        "model_name": model_name,
    })
    return flash(response, "success", "설정이 저장되었습니다.")


@router.post("/reports/{filename:path}/delete")
async def delete_report_route(
    request: Request,
    filename: str,
    user=Depends(require_user),
):
    success = delete_report(str(user.id), filename)
    response = RedirectResponse(url="/dashboard", status_code=302)
    if success:
        return flash(response, "success", "보고서가 삭제되었습니다.")
    return flash(response, "error", "보고서 삭제에 실패했습니다.")


@router.get("/reports/{filename:path}", response_class=HTMLResponse)
async def view_report(
    request: Request,
    filename: str,
    user=Depends(require_user),
):
    content = get_report_content(str(user.id), filename)
    from services.storage_service import get_report_logs
    logs = get_report_logs(str(user.id), filename)
    if not content:
        response = RedirectResponse(url="/dashboard", status_code=302)
        return flash(response, "error", "보고서를 불러오지 못했습니다.")

    topic = topic_from_filename(filename)

    return templates.TemplateResponse("report.html", {
        "request": request,
        "user": user,
        "content": content,
        "logs": logs,
        "topic": topic,
        "filename": filename,
        "messages": [],
    })
