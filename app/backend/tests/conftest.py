"""
Test infrastructure: in-memory SQLite DB, patched engine, AsyncClient fixture.

CRITICAL ORDER: patch models.database BEFORE importing main, otherwise the
module-level engine is already bound to the real DB file.
"""
import sys
import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Patch engine BEFORE any import of main or routers ---
import models.database as _db_module

TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TEST_SESSION_FACTORY = sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)

_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION_FACTORY

# Now safe to import main
from main import app  # noqa: E402
from models.database import init_db, get_db  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402


# Override get_db dependency to use test session factory
async def _override_get_db():
    async with TEST_SESSION_FACTORY() as session:
        yield session

app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(scope="session")
async def init_database():
    """Create all tables + seed settings once per session."""
    await init_db()
    yield


@pytest_asyncio.fixture(scope="session")
async def client(init_database):
    """HTTP test client bound to the FastAPI app with in-memory DB."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db_session():
    """Direct DB session for seeding test data."""
    async with TEST_SESSION_FACTORY() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_video(db_session):
    """
    Insert a fully-processed Video + SubtitleFormatted row.
    Returns dict with video_id (YouTube ID), db_id (UUID), formatted_text.
    """
    from models.models import Video, SubtitleFormatted

    video = Video(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_id="dQw4w9WgXcQ",
        title="Test Video",
        author="Test Author",
        duration=180,
    )
    db_session.add(video)
    await db_session.flush()

    fmt = SubtitleFormatted(
        video_id=video.id,
        language="ru",
        formatted_text="Привет всем.\n\nСегодня поговорим о Python.\n\nЭто мощный язык программирования.",
        text_length=80,
        processing_status="success",
    )
    db_session.add(fmt)
    await db_session.commit()

    yield {"video_id": "dQw4w9WgXcQ", "db_id": video.id, "fmt_id": fmt.id}

    # Cleanup — delete in reverse FK order
    await db_session.delete(fmt)
    await db_session.delete(video)
    await db_session.commit()
