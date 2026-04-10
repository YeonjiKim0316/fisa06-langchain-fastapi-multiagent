import logging
from urllib.parse import quote
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import Response
from core.dependencies import require_user
from core.utils import topic_from_filename
from services.storage_service import get_report_content
from services.pdf_service import generate_pdf

router = APIRouter(prefix="/pdf", tags=["pdf"])
logger = logging.getLogger("fisaai6-multi-agent.pdf")


@router.post("/generate")
async def pdf_from_form(
    request: Request,
    topic: str = Form(...),
    content: str = Form(...),
    user=Depends(require_user),
):
    """POST로 전달된 마크다운 콘텐츠로 PDF를 생성한다 (generate 페이지에서 사용)."""
    try:
        pdf_bytes = generate_pdf(content, topic)
        filename = topic.replace(" ", "_")[:60] + "_report.pdf"
        encoded_filename = quote(filename)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_filename}"},
        )
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return Response(content=f"PDF 생성 오류: {e}", status_code=500)


@router.get("/reports/{filename:path}/pdf")
async def pdf_from_storage(
    request: Request,
    filename: str,
    user=Depends(require_user),
):
    """로컬/S3 스토리지에서 저장된 보고서를 불러와 PDF를 생성한다."""
    content = get_report_content(str(user.id), filename)
    if not content:
        return Response(content="보고서를 찾을 수 없습니다.", status_code=404)

    topic = topic_from_filename(filename)

    try:
        pdf_bytes = generate_pdf(content, topic)
        fname = topic.replace(" ", "_")[:60] + "_report.pdf"
        encoded_fname = quote(fname)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_fname}"},
        )
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return Response(content=f"PDF 생성 오류: {e}", status_code=500)


@router.get("/reports/{filename:path}/markdown")
async def markdown_download(
    request: Request,
    filename: str,
    user=Depends(require_user),
):
    """저장된 보고서의 원본 마크다운을 다운로드한다."""
    content = get_report_content(str(user.id), filename)
    if not content:
        return Response(content="보고서를 찾을 수 없습니다.", status_code=404)
    basename = filename.split("/")[-1]
    encoded_basename = quote(basename)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{encoded_basename}"},
    )
