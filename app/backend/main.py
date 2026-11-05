import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models.database import init_db
from services.http_client import ssl_context
from models import models  # noqa: F401 — registers models with Base.metadata
from routers.api import router as api_router

# ---------------------------------------------------------------------------
# Logging — write to console + file (robust against uvicorn pre-configuration)
# ---------------------------------------------------------------------------
# YT_SUMMARIZER_LOG_DIR lets the test suite write somewhere else, so pytest never pollutes the live log
_log_dir = os.path.abspath(os.environ.get("YT_SUMMARIZER_LOG_DIR")
                           or os.path.join(os.path.dirname(__file__), "../../data/logs"))
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "backend.log")

_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(_log_fmt)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)

# Attach handlers directly to our service loggers — bypasses uvicorn's root config
for _name in ("services.text_summarizer", "services.text_cleaner", "services.subtitle_extractor",
               "services.video_service", "services.benchmark_service",
               "services.text_mindmapper", "mindmapper", "api.mindmap", "api.reextract", "api",
               "queue_service", "services.transcriber"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.INFO)
    _lg.propagate = False  # не пробрасывать в root (uvicorn не перехватит)
    _lg.addHandler(_console_handler)
    _lg.addHandler(_file_handler)

# Suppress SQLAlchemy SQL statement spam — only show warnings and above
for _name in ("sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool",
               "sqlalchemy.dialects", "sqlalchemy.orm"):
    logging.getLogger(_name).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.queue_service import queue_worker
    await init_db()
    await asyncio.to_thread(ssl_context)  # build the shared SSL context off the event loop (NS-28 item 3)
    await _reset_stale_statuses()
    await _cleanup_uploads_on_start()
    worker_task = asyncio.create_task(queue_worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


async def _reset_stale_statuses() -> None:
    """On startup, reset pipeline statuses stuck at 'processing' from a previous crash."""
    try:
        from models.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    UPDATE subtitles_formatted
                    SET
                        cleanup_status = CASE WHEN cleanup_status = 'processing' THEN NULL ELSE cleanup_status END,
                        summary_status = CASE WHEN summary_status = 'processing' THEN NULL ELSE summary_status END,
                        mindmap_status = CASE WHEN mindmap_status = 'processing' THEN NULL ELSE mindmap_status END
                    WHERE cleanup_status = 'processing'
                       OR summary_status = 'processing'
                       OR mindmap_status = 'processing'
                """)
            )
            if result.rowcount:
                logging.getLogger("api").warning(
                    "startup: reset %d row(s) with stale 'processing' status in subtitles_formatted",
                    result.rowcount,
                )
            await db.commit()
    except Exception as exc:
        logging.getLogger("api").warning("startup: stale-status reset failed: %s", exc)


async def _cleanup_uploads_on_start() -> None:
    """On startup, delete upload files older than upload_auto_delete_days if policy is 'after_days'."""
    try:
        from models.database import AsyncSessionLocal
        from services.video_service import get_app_setting
        from routers.settings import _cleanup_old_uploads
        async with AsyncSessionLocal() as db:
            auto_delete = await get_app_setting(db, "upload_auto_delete") or "false"
            mode = await get_app_setting(db, "upload_auto_delete_mode") or "immediate"
            days_str = await get_app_setting(db, "upload_auto_delete_days") or "7"
        if auto_delete == "true" and mode == "after_days":
            days = max(1, int(days_str))
            deleted = await asyncio.to_thread(_cleanup_old_uploads, days)
            if deleted:
                logging.getLogger("api").info("startup: cleaned %d upload(s) older than %d days", deleted, days)
    except Exception as exc:
        logging.getLogger("api").warning("startup: upload cleanup failed: %s", exc)


app = FastAPI(
    title="YT Summarizer API",
    description="Extract and format YouTube video subtitles",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

@app.exception_handler(Exception)
async def _log_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """uvicorn prints a crashed request to the console only; put it into backend.log with its traceback."""
    logging.getLogger("api").error("unhandled error in %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


@app.get("/")
async def root():
    return {"status": "operational", "service": "yt-summarizer"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
