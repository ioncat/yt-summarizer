from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

DATABASE_URL = f"sqlite+aiosqlite:///{settings.database_path}"

engine = create_async_engine(DATABASE_URL, echo=settings.debug)

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
    ]
    async with engine.begin() as conn:
        for table, column, sql in migrations:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result.fetchall()}
            if column not in existing:
                await conn.execute(text(sql))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_db()
