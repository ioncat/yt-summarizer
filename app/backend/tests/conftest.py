"""
Test infrastructure: in-memory SQLite DB, patched engine, AsyncClient fixture.

CRITICAL ORDER: patch models.database BEFORE importing main, otherwise the
module-level engine is already bound to the real DB file.
"""
import sys
import os
import tempfile
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# main.py attaches its log file when it is imported: point it at a temp folder BEFORE that import, so a test
# run never writes into the live data/logs/backend.log
os.environ["YT_SUMMARIZER_LOG_DIR"] = tempfile.mkdtemp(prefix="yt-summarizer-test-logs-")

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


# Uploaded files: like the database, never the live folder (rule 19). Every place that names the upload folder is pointed at a temp
# folder for the whole run; a test that wants its own folder still patches these (see the `uploads` fixture in
# test_baseline_file_stt.py). LIVE_UPLOADS is only used by the guard below.
TEST_UPLOADS = tempfile.mkdtemp(prefix="yt-summarizer-test-uploads-")
LIVE_UPLOADS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../data/uploads"))

import routers.process as _r_process  # noqa: E402
import routers.result_stages as _r_result_stages  # noqa: E402
import routers.settings as _r_settings  # noqa: E402
import services.file_stt as _s_file_stt  # noqa: E402

_s_file_stt.uploads_dir = lambda: TEST_UPLOADS
_r_process.uploads_dir = lambda: TEST_UPLOADS
_r_settings._uploads_dir = lambda: TEST_UPLOADS
_r_result_stages._uploads_dir = lambda: TEST_UPLOADS     # (trigger_reextract looks for the original file)


def _snapshot_uploads(path: str) -> list:
    if not os.path.isdir(path):
        return []
    return sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in os.scandir(path))


def describe_uploads_change(before: list, after: list) -> str:
    b, a = {n: (size, mtime) for n, size, mtime in before}, {n: (size, mtime) for n, size, mtime in after}
    return "added %s, removed %s, changed %s" % (
        sorted(set(a) - set(b)), sorted(set(b) - set(a)), sorted(n for n in set(a) & set(b) if a[n] != b[n]))


@pytest.fixture(scope="session", autouse=True)
def _live_uploads_untouched():
    """Guard: the run must leave the LIVE app/data/uploads exactly as it found it (names, sizes, times). If the live app took an
    upload while the suite ran, this reports it too: run the suite again."""
    before = _snapshot_uploads(LIVE_UPLOADS)
    yield
    after = _snapshot_uploads(LIVE_UPLOADS)
    assert after == before, "the test run changed the live uploads folder %s: %s" % (LIVE_UPLOADS, describe_uploads_change(before, after))


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

    # Cleanup — delete in reverse FK order (and the per-stage runs the test left for this video id)
    from sqlalchemy import text
    await db_session.execute(text("DELETE FROM processing_stages WHERE video_id = 'dQw4w9WgXcQ'"))
    await db_session.delete(fmt)
    await db_session.delete(video)
    await db_session.commit()


# --- order options (NS-22): the suite must pass in any order -------------------------------------------------------------
def pytest_addoption(parser):
    parser.addoption("--reverse", action="store_true", default=False, help="run the tests in reverse order")
    parser.addoption("--shuffle", action="store", default=None, metavar="SEED", help="run the tests in a random order (seed)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--reverse"):
        items.reverse()
    seed = config.getoption("--shuffle")
    if seed is not None:
        import random
        random.Random(int(seed)).shuffle(items)


# --- every test starts from the seeded settings and an empty data set (NS-22) ------------------------------------------------
# The test database lives for the whole session. A test that sets a model, an Ollama URL or a prompt, or leaves a queue item, a
# task or a video behind, used to hand it to every test after it, so the result depended on the order. After each test the
# settings tables are put back as they were seeded and the data tables are emptied.
_DATA_TABLES = ("processing_stages", "processing_queue", "processing_tasks", "benchmark_runs",
                "subtitles_raw", "subtitles_formatted", "videos")      # (children first)
_SETTINGS_TABLES = ("app_settings", "pipeline_settings")
_SETTINGS_BASELINE: dict[str, list[dict]] = {}


async def _read_settings() -> dict[str, list[dict]]:
    from sqlalchemy import text
    async with TEST_SESSION_FACTORY() as session:
        return {t: sorted((dict(r) for r in (await session.execute(text(f"SELECT * FROM {t}"))).mappings()),
                          key=lambda row: str(sorted(row.items()))) for t in _SETTINGS_TABLES}


@pytest_asyncio.fixture(autouse=True)
async def _state_is_restored(init_database):
    from sqlalchemy import text
    if not _SETTINGS_BASELINE:
        _SETTINGS_BASELINE.update(await _read_settings())
    yield
    async with TEST_SESSION_FACTORY() as session:
        for table in _DATA_TABLES:
            await session.execute(text(f"DELETE FROM {table}"))
        await session.commit()
    now = await _read_settings()
    for table in _SETTINGS_TABLES:
        if now[table] == _SETTINGS_BASELINE[table]:
            continue
        async with TEST_SESSION_FACTORY() as session:
            await session.execute(text(f"DELETE FROM {table}"))
            for row in _SETTINGS_BASELINE[table]:
                cols = ", ".join(row)
                await session.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({', '.join(':' + c for c in row)})"), row)
            await session.commit()
