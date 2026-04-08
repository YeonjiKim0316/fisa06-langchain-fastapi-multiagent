import json
import re
from fastapi.responses import RedirectResponse


def flash(response: RedirectResponse, category: str, message: str) -> RedirectResponse:
    """단발성 플래시 메시지를 단기 쿠키에 저장한다 (JS에서 1회 읽음)."""
    response.set_cookie(
        "flash",
        json.dumps([[category, message]]),
        max_age=10,
        httponly=False,
        samesite="lax",
    )
    return response


def topic_from_filename(filename: str) -> str:
    """스토리지 파일명에서 사람이 읽을 수 있는 토픽명을 추출한다."""
    basename = filename.split("/")[-1].replace(".md", "")
    return re.sub(r'_\d{8}_\d{6}$', '', basename).replace('_', ' ')
