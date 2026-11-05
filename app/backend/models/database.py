import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

logger = logging.getLogger("api")

DATABASE_URL = f"sqlite+aiosqlite:///{settings.database_path}"

BUSY_TIMEOUT_MS = 30_000


def _apply_sqlite_pragmas(dbapi_connection, _record=None) -> None:
    """Per-connection SQLite settings (NS-28 item 1). Idempotent: it runs on every new connection.

    journal_mode=WAL    readers no longer block the writer (and the writer no longer blocks readers); the mode is
                        stored in the database file, so setting it again on a WAL file changes nothing. Creates the
                        side files <db>-wal and <db>-shm next to the database.
    busy_timeout        a writer waits up to 30 s for the lock instead of 5 s before "database is locked".
    synchronous=NORMAL  with WAL, a commit is not fsynced on every transaction (a crash can lose the last commits of the
                        last moments, never corrupt the file).
    One failing pragma (e.g. WAL cannot be switched while another program has the file open) is logged and skipped.
    """
    cursor = dbapi_connection.cursor()
    try:
        for pragma in ("PRAGMA journal_mode=WAL", f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}", "PRAGMA synchronous=NORMAL"):
            try:
                cursor.execute(pragma)
                cursor.fetchall()
            except Exception as exc:  # noqa: BLE001
                logger.warning("sqlite: %s failed: %s", pragma, exc)
    finally:
        cursor.close()


def create_engine_for(url: str):
    """The app's async engine for `url` with the SQLite settings applied to every connection."""
    new_engine = create_async_engine(url, echo=False, connect_args={"timeout": BUSY_TIMEOUT_MS / 1000})
    event.listen(new_engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return new_engine


engine = create_engine_for(DATABASE_URL)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _migrate_db() -> None:
    """Add new columns to existing tables (lightweight alternative to Alembic)."""
    from sqlalchemy import text
    migrations = [
        ("subtitles_formatted", "cleaned_text", "ALTER TABLE subtitles_formatted ADD COLUMN cleaned_text TEXT"),
        ("subtitles_formatted", "cleanup_status", "ALTER TABLE subtitles_formatted ADD COLUMN cleanup_status TEXT"),
        ("subtitles_formatted", "cleanup_started_at", "ALTER TABLE subtitles_formatted ADD COLUMN cleanup_started_at DATETIME"),
        ("subtitles_formatted", "cleanup_finished_at", "ALTER TABLE subtitles_formatted ADD COLUMN cleanup_finished_at DATETIME"),
        ("subtitles_formatted", "cleanup_model", "ALTER TABLE subtitles_formatted ADD COLUMN cleanup_model TEXT"),
        ("subtitles_formatted", "summary_text", "ALTER TABLE subtitles_formatted ADD COLUMN summary_text TEXT"),
        ("subtitles_formatted", "summary_status", "ALTER TABLE subtitles_formatted ADD COLUMN summary_status TEXT"),
        ("subtitles_formatted", "summary_started_at", "ALTER TABLE subtitles_formatted ADD COLUMN summary_started_at DATETIME"),
        ("subtitles_formatted", "summary_finished_at", "ALTER TABLE subtitles_formatted ADD COLUMN summary_finished_at DATETIME"),
        ("subtitles_formatted", "summary_model", "ALTER TABLE subtitles_formatted ADD COLUMN summary_model TEXT"),
        ("subtitles_formatted", "summary_mode", "ALTER TABLE subtitles_formatted ADD COLUMN summary_mode TEXT"),
        ("subtitles_formatted", "summary_chunks_count", "ALTER TABLE subtitles_formatted ADD COLUMN summary_chunks_count INTEGER"),
        ("videos", "chapters", "ALTER TABLE videos ADD COLUMN chapters TEXT"),
        ("benchmark_runs", "triggered_by", "ALTER TABLE benchmark_runs ADD COLUMN triggered_by TEXT DEFAULT 'benchmark'"),
        ("subtitles_formatted", "chat_history", "ALTER TABLE subtitles_formatted ADD COLUMN chat_history TEXT"),
        ("subtitles_formatted", "mindmap_text", "ALTER TABLE subtitles_formatted ADD COLUMN mindmap_text TEXT"),
        ("subtitles_formatted", "mindmap_status", "ALTER TABLE subtitles_formatted ADD COLUMN mindmap_status TEXT"),
        ("videos", "is_favorite", "ALTER TABLE videos ADD COLUMN is_favorite BOOLEAN DEFAULT 0"),
        ("processing_queue", "language", "ALTER TABLE processing_queue ADD COLUMN language TEXT"),
        ("subtitles_formatted", "subtitle_source", "ALTER TABLE subtitles_formatted ADD COLUMN subtitle_source TEXT DEFAULT 'captions'"),
        ("subtitles_formatted", "transcription_started_at", "ALTER TABLE subtitles_formatted ADD COLUMN transcription_started_at DATETIME"),
        ("subtitles_formatted", "transcription_finished_at", "ALTER TABLE subtitles_formatted ADD COLUMN transcription_finished_at DATETIME"),
        ("subtitles_formatted", "transcription_model", "ALTER TABLE subtitles_formatted ADD COLUMN transcription_model TEXT"),
        ("subtitles_formatted", "transcription_device", "ALTER TABLE subtitles_formatted ADD COLUMN transcription_device TEXT"),
        ("subtitles_formatted", "cleanup_error", "ALTER TABLE subtitles_formatted ADD COLUMN cleanup_error TEXT"),
        ("subtitles_formatted", "summary_error", "ALTER TABLE subtitles_formatted ADD COLUMN summary_error TEXT"),
        ("subtitles_formatted", "mindmap_error", "ALTER TABLE subtitles_formatted ADD COLUMN mindmap_error TEXT"),
    ]
    async with engine.begin() as conn:
        for table, column, sql in migrations:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result.fetchall()}
            if column not in existing:
                await conn.execute(text(sql))


async def _seed_app_settings() -> None:
    """Seed default app settings on first launch if table is empty."""
    from sqlalchemy import text
    from config import settings as cfg
    defaults = {
        "ollama_url": cfg.ollama_url,
        "ytdlp_path": cfg.ytdlp_path,
        "cookies_path": cfg.cookies_path,
        "force_map_reduce": "false",
        "parallel_workers": "1",
        "queue_default_pipeline": '["extract"]',
        "stt_engine": "faster-whisper",
        "stt_model": "base",
        "stt_device": "auto",
        "stt_cache_path": "",
        "upload_auto_delete": "false",
        "upload_auto_delete_mode": "immediate",
        "upload_auto_delete_days": "7",
        "chat_num_ctx": "32768",
        "llm_max_num_ctx": "32768",
        "download_default_format": "mp4",
        "download_default_quality": "best",
    }
    async with AsyncSessionLocal() as session:
        for key, value in defaults.items():
            exists = await session.execute(
                text("SELECT 1 FROM app_settings WHERE key = :key"), {"key": key}
            )
            if not exists.scalar():
                await session.execute(
                    text("INSERT INTO app_settings (key, value, updated_at) VALUES (:key, :value, datetime('now'))"),
                    {"key": key, "value": value},
                )
        await session.commit()


async def _backfill_stages() -> None:
    """Fill processing_stages from the old per-stage columns (NS-25). Idempotent; a failure is logged, never fatal."""
    from services.stage_backfill import backfill_processing_stages
    try:
        async with engine.begin() as conn:
            await backfill_processing_stages(conn)
    except Exception:  # noqa: BLE001
        logger.exception("startup: filling processing_stages failed (the old columns are untouched)")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_db()
    await _seed_app_settings()
    await _backfill_stages()
