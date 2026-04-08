import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from core.dependencies import get_current_user
from core.utils import flash
from services.auth_service import sign_in, sign_up, sign_out

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("deepresearch.auth")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request, "user": None, "messages": []})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    try:
        user, token = sign_in(email, password)
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24,  # 24시간
        )
        return response
    except Exception as e:
        logger.warning(f"Login failed for {email}: {e}")
        response = RedirectResponse(url="/auth/login", status_code=302)
        return flash(response, "error", str(e))


@router.post("/signup")
async def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
):
    try:
        user, token = sign_up(email, password, full_name)
        response = RedirectResponse(url="/dashboard", status_code=302)
        if token:
            response.set_cookie(
                key="access_token",
                value=token,
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 24,
            )
        else:
            # 이메일 인증 필요
            response = RedirectResponse(url="/auth/login?tab=signup", status_code=302)
            flash(response, "success", "회원가입 완료! 이메일을 확인하여 계정을 인증해주세요.")
        return response
    except Exception as e:
        logger.warning(f"Signup failed for {email}: {e}")
        response = RedirectResponse(url="/auth/login?tab=signup", status_code=302)
        return flash(response, "error", str(e))


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("access_token")
    sign_out(token)
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token")
    response.delete_cookie("session")
    return response
