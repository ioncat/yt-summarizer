from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

DATABASE_URL = f"sqlite+aiosqlite:///{settings.database_path}"

engine = create_async_engine(DATABASE_URL, echo=False)

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


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_db()
    await _seed_app_settings()
