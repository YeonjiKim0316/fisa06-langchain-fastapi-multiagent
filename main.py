import os
import logging
from dotenv import load_dotenv
load_dotenv(f".env.{os.environ.get('APP_ENV', 'local')}")
load_dotenv(".env", override=True)

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("deepresearch")

# Silence noisy msgpack warning from langgraph
logging.getLogger("langgraph.checkpoint.serde.jsonplus").setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.storage_service import ensure_bucket
    from deep_ai.agent import init_checkpointer, close_checkpointer
    ensure_bucket()
    await init_checkpointer()
    try:
        yield
    finally:
        try:
            await close_checkpointer()
        except Exception:
            pass


app = FastAPI(title="FISA AI-Multi Agentic DeepResearcher", version="2.0.0", lifespan=lifespan)

# 정적 파일 마운트
app.mount("/static", StaticFiles(directory="static"), name="static")

# 템플릿 (라우터에서 공유 사용)
templates = Jinja2Templates(directory="templates")

# 라우터 — 순환 임포트 방지를 위해 app 생성 이후 임포트
from routers import auth, reports, generate, pdf  # noqa: E402

app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(generate.router)
app.include_router(pdf.router)


@app.exception_handler(StarletteHTTPException)
async def redirect_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 302 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=302)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})


@app.get("/")
async def root():
    return RedirectResponse(url="/auth/login")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
