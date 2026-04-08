"""
itsdangerous를 이용한 서명 쿠키 세션 헬퍼.
사용자별 설정 및 API 키를 서명된 쿠키에 저장한다.
"""
import json
from itsdangerous import URLSafeSerializer
from fastapi import Request
from fastapi.responses import Response
from core.config import get_settings

_COOKIE_NAME = "session"
_MAX_AGE = 60 * 60 * 24  # 24시간
_serializer = URLSafeSerializer(get_settings().secret_key, salt="session")


def get_session(request: Request) -> dict:
    raw = request.cookies.get(_COOKIE_NAME)
    if not raw:
        return {}
    try:
        return _serializer.loads(raw)
    except Exception:
        return {}


def set_session(response: Response, data: dict) -> None:
    signed = _serializer.dumps(data)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=signed,
        httponly=True,
        samesite="lax",
        max_age=_MAX_AGE,
    )


def update_session(request: Request, response: Response, updates: dict) -> dict:
    """기존 세션에 업데이트 내용을 병합하고 저장한다."""
    session = get_session(request)
    session.update(updates)
    set_session(response, session)
    return session
