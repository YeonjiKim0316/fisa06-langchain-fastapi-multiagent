from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from services.auth_service import get_user_from_token


def get_current_user(request: Request):
    """
    'access_token' 쿠키를 읽어 PyJWT로 검증한다.
    유저 객체 또는 None을 반환한다.
    """
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_user_from_token(token)


def require_user(request: Request):
    """
    get_current_user와 동일하나, 미인증 시 /auth/login으로 리다이렉트한다.
    보호된 라우트에서 FastAPI Depends()로 사용한다.
    """
    user = get_current_user(request)
    if not user:
        # 리다이렉트를 예외로 발생시켜 FastAPI가 깔끔하게 처리하도록 함
        raise StarletteHTTPException(
            status_code=302,
            headers={"Location": "/auth/login"},
        )
    return user
