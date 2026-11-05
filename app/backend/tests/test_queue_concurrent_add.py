"""NS-28 review: adding the same link at the same moment gives one queue row, not several.

Before: the duplicate check and the insert were separate steps, so N identical adds sent together all passed the check
(probe: 2 concurrent adds -> 2 rows, 5 -> 5 rows). Now every insert checks and writes in one statement.
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from models import database as dbm
from models.database import AsyncSessionLocal
from models.models import Base, Video
from services import queue_service as q
from tests.baseline_helpers import reset_queue

URL = "https://www.youtube.com/watch?v=concAdd0001"


@pytest_asyncio.fixture(autouse=True)
async def _clean(client):
    await reset_queue()
    yield
    await reset_queue()


async def _rows(video_id=None):
    async with AsyncSessionLocal() as db:
        sql = "SELECT id, video_id, sort_order, status FROM processing_queue"
        params = {}
        if video_id:
            sql += " WHERE video_id = :v"
            params = {"v": video_id}
        return (await db.execute(text(sql), params)).fetchall()


# --- through the endpoint (one shared test connection) -----------------------------------------

@pytest.mark.parametrize("n", [2, 5])
async def test_identical_adds_sent_together_give_one_row(client, n):
    results = await asyncio.gather(*(
        client.post("/api/queue/bulk", json={"urls": [URL], "pipeline_stages": ["extract"]}) for _ in range(n)))
    bodies = [r.json() for r in results]
    assert all(r.status_code == 200 for r in results)
    assert sorted(b["added"] for b in bodies) == [0] * (n - 1) + [1]
    assert len(await _rows("concAdd0001")) == 1
    for loser in (b for b in bodies if b["added"] == 0):
        assert loser["duplicates"] == [URL]
        assert loser["duplicate_details"] == [{"url": URL, "video_id": "concAdd0001", "reason": "in_queue"}]


async def test_different_links_sent_together_are_all_added_with_their_own_sort_order(client):
    urls = [f"https://www.youtube.com/watch?v=concD{i:06d}" for i in range(6)]
    results = await asyncio.gather(*(client.post("/api/queue/bulk", json={"urls": [u]}) for u in urls))
    assert all(r.json()["added"] == 1 for r in results)
    rows = await _rows()
    assert len(rows) == 6
    assert len({r[2] for r in rows}) == 6                       # no two rows share a sort_order
    assert sorted(r[2] for r in rows) == list(range(min(r[2] for r in rows), min(r[2] for r in rows) + 6))  # no gaps


async def test_a_batch_with_a_link_that_is_queued_meanwhile_adds_the_rest(client):
    await client.post("/api/queue/bulk", json={"urls": [URL]})
    other = "https://www.youtube.com/watch?v=concOther01"
    async with AsyncSessionLocal() as db:   # the endpoint's own check ran before: call the insert step directly
        ids, skipped = await q.add_items_unique(db, [URL, other], ["extract"])
    assert len(ids) == 1 and skipped == [(URL, "concAdd0001")]
    assert len(await _rows("concAdd0001")) == 1 and len(await _rows("concOther01")) == 1


async def test_force_still_allows_a_second_row_for_a_link_that_is_already_queued(client):
    await client.post("/api/queue/bulk", json={"urls": [URL]})
    r = await client.post("/api/queue/bulk", json={"urls": [URL], "force": True})
    assert r.json()["added"] == 1 and len(await _rows("concAdd0001")) == 2   # force = "skip the duplicate check"


async def test_a_finished_item_does_not_block_adding_the_link_again(client):
    await client.post("/api/queue/bulk", json={"urls": [URL]})
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE processing_queue SET status = 'done'"))
        await db.commit()
    assert (await client.post("/api/queue/bulk", json={"urls": [URL]})).json()["added"] == 1


async def test_by_id_adds_sent_together_give_one_row(client, seeded_video):
    vid = seeded_video["video_id"]
    body = {"video_ids": [vid], "pipeline_stages": ["cleanup"]}
    results = await asyncio.gather(*(client.post("/api/queue/bulk", json=body) for _ in range(5)))
    assert sorted(r.json()["added"] for r in results) == [0, 0, 0, 0, 1]
    assert len(await _rows(vid)) == 1
    assert all(r.json()["duplicates"] == [vid] for r in results if r.json()["added"] == 0)


# --- real separate connections (a file database in WAL mode, like the live one) --------------------

@pytest_asyncio.fixture
async def file_db(tmp_path):
    engine = dbm.create_engine_for(f"sqlite+aiosqlite:///{tmp_path / 'conc.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def test_five_sessions_on_five_connections_adding_the_same_link_make_one_row(file_db):
    async def one():
        async with file_db() as db:
            return await q.add_items_unique(db, [URL], ["extract"])

    results = await asyncio.gather(*(one() for _ in range(5)))
    assert sum(len(ids) for ids, _ in results) == 1
    assert sum(len(skipped) for _, skipped in results) == 4
    async with file_db() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM processing_queue"))).scalar() == 1


async def test_five_sessions_adding_the_same_id_by_id_make_one_row(file_db):
    from services.queue_by_id import add_by_video_ids
    async with file_db() as db:
        db.add(Video(url="local://talk.m4a", video_id="file-conc0001", title="talk.m4a"))
        await db.commit()

    async def one():
        async with file_db() as db:
            return await add_by_video_ids(db, ["file-conc0001"], ["cleanup"])

    results = await asyncio.gather(*(one() for _ in range(5)))
    assert sum(len(r["ids"]) for r in results) == 1
    assert sum(len(r["duplicates"]) for r in results) == 4
    async with file_db() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM processing_queue"))).scalar() == 1


async def test_sessions_on_separate_connections_get_distinct_sort_orders(file_db):
    async def one(i):
        async with file_db() as db:
            return await q.add_items_unique(db, [f"https://www.youtube.com/watch?v=sortOrd{i:04d}"], ["extract"])

    await asyncio.gather(*(one(i) for i in range(8)))
    async with file_db() as db:
        orders = [r[0] for r in (await db.execute(text("SELECT sort_order FROM processing_queue"))).fetchall()]
    assert len(orders) == 8 and sorted(orders) == list(range(1, 9))
