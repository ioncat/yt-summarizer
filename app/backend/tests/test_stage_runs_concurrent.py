"""NS-25 review fix: concurrent begin() on a FILE database gives exactly one open run (the shared in-memory test database
cannot show this: one connection, no real concurrency)."""
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from models.database import create_engine_for
from models.models import ProcessingStage
from services import stage_runs


@pytest.fixture
async def file_db(tmp_path):
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ProcessingStage.__table__.create(c))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _begin(factory, stage="summary", qid=None):
    async with factory() as db:
        row = await stage_runs.begin(db, "vid", stage, "m", qid)
        await db.commit()
        return row


async def _rows(factory, stage="summary"):
    async with factory() as db:
        return [dict(r) for r in (await db.execute(
            text("SELECT * FROM processing_stages WHERE video_id = 'vid' AND stage = :s ORDER BY id"), {"s": stage})).mappings().all()]


async def test_five_concurrent_begins_give_one_open_row(file_db):
    ids = await asyncio.gather(*[_begin(file_db) for _ in range(5)])
    assert len(set(ids)) == 1
    rows = await _rows(file_db)
    assert [(r["status"], r["attempt"]) for r in rows] == [("processing", 1)]


async def test_concurrent_begins_with_item_ids_keep_one_row_and_fill_in_the_item(file_db):
    await asyncio.gather(*[_begin(file_db, qid=q) for q in (None, 4, None, 4)])
    (row,) = await _rows(file_db)
    assert row["queue_item_id"] == 4


async def test_attempts_count_up_across_runs_and_stages_do_not_share_an_open_row(file_db):
    await _begin(file_db)
    async with file_db() as db:
        await stage_runs.finish(db, "vid", "summary")
        await db.commit()
    await asyncio.gather(*[_begin(file_db) for _ in range(3)])
    await _begin(file_db, stage="cleanup")
    assert [(r["status"], r["attempt"]) for r in await _rows(file_db)] == [("done", 1), ("processing", 2)]
    assert len(await _rows(file_db, "cleanup")) == 1


async def test_the_unique_index_refuses_a_second_open_row_even_for_a_raw_insert(file_db):
    await _begin(file_db)
    async with file_db() as db:
        with pytest.raises(IntegrityError):
            await db.execute(text("INSERT INTO processing_stages (video_id, stage, status, attempt, created_at) "
                                  "VALUES ('vid', 'summary', 'processing', 9, datetime('now'))"))


async def test_the_start_up_step_closes_old_duplicates_and_adds_the_index_to_an_existing_table(tmp_path):
    """A database made before the index existed, with duplicate open rows left by concurrent begins."""
    engine = create_engine_for(f"sqlite+aiosqlite:///{tmp_path / 'old.sqlite'}")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE processing_stages (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id VARCHAR NOT NULL, "
            "stage VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL, queue_item_id INTEGER, attempt INTEGER NOT NULL, "
            "model VARCHAR, started_at DATETIME, finished_at DATETIME, error_code VARCHAR(40), error_text TEXT, meta TEXT, "
            "progress_done INTEGER, progress_total INTEGER, created_at DATETIME NOT NULL)"))
        for _ in range(3):
            await conn.execute(text("INSERT INTO processing_stages (video_id, stage, status, attempt, created_at) "
                                    "VALUES ('vid', 'summary', 'processing', 1, datetime('now'))"))
        await conn.execute(text("INSERT INTO processing_stages (video_id, stage, status, attempt, created_at) "
                                "VALUES ('vid', 'cleanup', 'processing', 1, datetime('now'))"))
    async with engine.begin() as conn:
        assert await stage_runs.ensure_open_run_index(conn) == 2
        assert await stage_runs.ensure_open_run_index(conn) == 0          # a second start changes nothing
        rows = (await conn.execute(text("SELECT id, status FROM processing_stages WHERE stage = 'summary' ORDER BY id"))).fetchall()
    assert [r[1] for r in rows] == ["cancelled", "cancelled", "processing"]     # the newest stays open
    async with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(text("INSERT INTO processing_stages (video_id, stage, status, attempt, created_at) "
                                    "VALUES ('vid', 'summary', 'processing', 2, datetime('now'))"))
    await engine.dispose()
