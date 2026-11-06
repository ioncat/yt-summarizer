"""Shared helpers for the NS-11 baseline tests (pin CURRENT pipeline behaviour)."""
import asyncio

from sqlalchemy import text

from models.database import AsyncSessionLocal

VIDEO_ID = "dQw4w9WgXcQ"  # same id as the seeded_video fixture


async def fmt_row(video_id: str = VIDEO_ID) -> dict | None:
    """Newest subtitles_formatted row of a video as a dict."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            text(
                "SELECT sf.* FROM subtitles_formatted sf JOIN videos v ON sf.video_id = v.id "
                "WHERE v.video_id = :v ORDER BY sf.created_at DESC LIMIT 1"
            ),
            {"v": video_id},
        )
        row = r.mappings().first()
        return dict(row) if row else None


async def fmt_count(video_id: str = VIDEO_ID) -> int:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            text(
                "SELECT COUNT(*) FROM subtitles_formatted sf JOIN videos v ON sf.video_id = v.id "
                "WHERE v.video_id = :v"
            ),
            {"v": video_id},
        )
        return r.scalar()


async def set_fmt(video_id: str = VIDEO_ID, **cols) -> None:
    """Set old per-stage columns of the newest row. The result API reads the stage table first (NS-25), so the runs of
    every stage whose columns are set here are dropped: the columns this test just wrote are then what the API says."""
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    async with AsyncSessionLocal() as db:
        for stage in ("cleanup", "summary", "mindmap"):
            if any(k.startswith(stage + "_") for k in cols):
                await db.execute(text("DELETE FROM processing_stages WHERE video_id = :v AND stage = :s"),
                                 {"v": video_id, "s": stage})
        await db.execute(
            text(
                f"UPDATE subtitles_formatted SET {sets} WHERE video_id IN "
                f"(SELECT id FROM videos WHERE video_id = :__vid)"
            ),
            {**cols, "__vid": video_id},
        )
        await db.commit()


async def benchmark_rows(stage: str, video_id: str = VIDEO_ID) -> list[dict]:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            text("SELECT * FROM benchmark_runs WHERE video_id = :v AND stage = :s"),
            {"v": video_id, "s": stage},
        )
        return [dict(x) for x in r.mappings().all()]


async def reset_benchmarks() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM benchmark_runs"))
        await db.commit()


async def wait_for_counters(stage: str, video_id: str = VIDEO_ID, timeout: float = 5.0) -> dict:
    """The open run row of `stage` once its live counters are written (they are written a moment after the callback)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        async with AsyncSessionLocal() as db:
            r = (await db.execute(
                text("SELECT * FROM processing_stages WHERE video_id = :v AND stage = :s AND status = 'processing' "
                     "AND progress_total IS NOT NULL ORDER BY id DESC LIMIT 1"), {"v": video_id, "s": stage})).mappings().first()
        if r:
            return dict(r)
        assert asyncio.get_event_loop().time() < deadline, f"no counters were written for {stage}"
        await asyncio.sleep(0.02)


async def reset_queue() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM processing_queue"))
        await db.commit()


class Gate:
    """A fake LLM call that blocks until released, so a test can look at the 'during' state."""

    def __init__(self, result="RESULT", progress=(1, 3)):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.result = result
        self.progress = progress
        self.calls: list[dict] = []

    def llm(self, positional_text_ok=True):
        async def fake(*args, **kwargs):
            self.calls.append({"args": args, **kwargs})
            if kwargs.get("on_progress"):
                kwargs["on_progress"](*self.progress)
            self.started.set()
            await self.release.wait()
            return self.result
        return fake

    async def wait_started(self):
        await asyncio.wait_for(self.started.wait(), 5)


def clear_router_state() -> None:
    from routers import result_stages as r
    for s in (r._CANCEL_SET, r._SUMMARY_CANCEL_SET, r._MINDMAP_CANCEL_SET):
        s.clear()
    from services import queue_service as q
    q._QUEUE_PROGRESS.clear()


# --- queue helpers for the stage tests (NS-11 stage 2 on) -------------------------------------------

async def add_item(stages, url=None, video_id=VIDEO_ID, language=None) -> int:
    """A pending queue item for an existing video, queued the way the app does it."""
    from services import queue_service as q
    async with AsyncSessionLocal() as db:
        return (await q.add_items(db, [url or f"https://www.youtube.com/watch?v={video_id}"], stages, language=language))[0]


async def run_queued_stage(video_id: str, stage: str) -> None:
    """Run the worker over the queued item(s) that hold only `stage` for this video (what the endpoint queued)."""
    from services import queue_service as q
    async with AsyncSessionLocal() as db:
        ids = [i["id"] for i in await q.get_queue(db)
               if i["video_id"] == video_id and i["pipeline_stages"] == [stage] and i["status"] == "pending"]
    if ids:
        await run_worker(ids)


async def run_extract_items(video_id: str) -> list[dict]:
    """Let the queue worker run the extract item(s) that POST /api/process queued for this video (NS-11 stage 7); returns the items
    as the worker left them."""
    from services import queue_service as q
    async with AsyncSessionLocal() as db:
        ids = [i["id"] for i in await q.get_queue(db)
               if i["video_id"] == video_id and i["pipeline_stages"] == ["extract"] and i["status"] == "pending"]
    if ids:
        await run_worker(ids)
    async with AsyncSessionLocal() as db:
        return [i for i in await q.get_queue(db) if i["id"] in ids]


async def run_reextract_items(video_id: str) -> list[dict]:
    """Let the queue worker run the re-extract item(s) of this video (NS-11 stage 6); returns the items as the worker left them."""
    from services import queue_service as q
    async with AsyncSessionLocal() as db:
        ids = [i["id"] for i in await q.get_queue(db)
               if i["video_id"] == video_id and i["pipeline_stages"] == ["reextract"] and i["status"] == "pending"]
    if ids:
        await run_worker(ids)
    async with AsyncSessionLocal() as db:
        return [i for i in await q.get_queue(db) if i["id"] in ids]


async def get_item(item_id: int) -> dict:
    from services import queue_service as q
    async with AsyncSessionLocal() as db:
        return next(i for i in await q.get_queue(db) if i["id"] == item_id)


async def run_worker(item_ids: list[int], timeout: float = 15.0) -> None:
    """Run the queue worker until every given item is done / partial / failed / skipped AND the worker has finished with it.

    Two traps of the shared in-memory test connection this avoids:
    - no polling of the database: a polling session that closes sends a ROLLBACK on the shared connection, which can
      undo a stage's UPDATE that is in flight;
    - no cancelling of the worker while it still writes (after marking an item failed it may tidy up statuses): a
      cancel inside a session closes the shared connection and the whole test database disappears.
    So the worker is cancelled only when it asks for its NEXT item, i.e. when it is idle between items.
    """
    from services import queue_service as q
    wanted = set(item_ids)
    finished: set[int] = set()
    idle = asyncio.Event()
    originals = {name: getattr(q, name) for name in ("_set_done", "_set_partial", "_set_failed", "_set_skipped", "_pick_next")}

    def wrap_finish(name):
        async def inner(item_id, *args, **kwargs):
            result = await originals[name](item_id, *args, **kwargs)
            finished.add(item_id)
            return result
        return inner

    async def pick_next():
        if wanted <= finished:        # everything asked for is finished and the worker is back at the top of its loop
            idle.set()
            return None
        return await originals["_pick_next"]()

    for name in ("_set_done", "_set_partial", "_set_failed", "_set_skipped"):
        setattr(q, name, wrap_finish(name))
    q._pick_next = pick_next

    class _FastAsyncio:               # the worker's pauses between items (1 s, 5 s) are not worth waiting for in a test
        def __getattr__(self, attr):
            return getattr(asyncio, attr)

        @staticmethod
        async def sleep(seconds, *args):
            await asyncio.sleep(min(seconds, 0.01), *args)

    real_asyncio = q.asyncio
    q.asyncio = _FastAsyncio()
    task = asyncio.create_task(q.queue_worker())
    try:
        try:
            await asyncio.wait_for(idle.wait(), timeout)
        except asyncio.TimeoutError:
            pass
    finally:
        q._WORKER_STOP = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        q._WORKER_STOP = False
        q.asyncio = real_asyncio
        for name, fn in originals.items():
            setattr(q, name, fn)
