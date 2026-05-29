import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models.database import init_db
from models import models  # noqa: F401 — registers models with Base.metadata
from routers.api import router as api_router

# ---------------------------------------------------------------------------
# Logging — write to console + file (robust against uvicorn pre-configuration)
# ---------------------------------------------------------------------------
_log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/logs"))
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "backend.log")

_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(_log_fmt)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)

# Attach handlers directly to our service loggers — bypasses uvicorn's root config
for _name in ("services.text_summarizer", "services.text_cleaner", "services.subtitle_extractor",
               "services.video_service", "services.benchmark_service", "routers.api",
               "services.text_mindmapper", "mindmapper", "api.mindmap",
               "queue_service"):
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
    import asyncio
    from services.queue_service import queue_worker
    await init_db()
    worker_task = asyncio.create_task(queue_worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="YT Summarizer API",
    description="Extract and format YouTube video subtitles",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

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
