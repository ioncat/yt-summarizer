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
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    async with AsyncSessionLocal() as db:
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
    from routers import result as r
    for s in (r._CANCEL_SET, r._SUMMARY_CANCEL_SET, r._MINDMAP_CANCEL_SET, r._REEXTRACT_SET):
        s.clear()
    for d in (r._CLEANUP_PROGRESS, r._SUMMARY_PROGRESS, r._RETRANSCRIBE_PROGRESS):
        d.clear()
    from services import queue_service as q
    q._QUEUE_PROGRESS.clear()


# --- queue helpers for the stage tests (NS-11 stage 2 on) -------------------------------------------

async def add_item(stages, url=None, video_id=VIDEO_ID, language=None) -> int:
    """A pending queue item for an existing video, queued the way the app does it."""
    from services import queue_service as q
    async with AsyncSessionLocal() as db:
        return (await q.add_items(db, [url or f"https://www.youtube.com/watch?v={video_id}"], stages, language=language))[0]


async def get_item(item_id: int) -> dict:
    from services import queue_service as q
    async with AsyncSessionLocal() as db:
        return next(i for i in await q.get_queue(db) if i["id"] == item_id)


async def run_worker(item_ids: list[int], timeout: float = 15.0) -> None:
    """Run the queue worker until every given item is done / failed / skipped (or the timeout)."""
    import time
    from services import queue_service as q
    task = asyncio.create_task(q.queue_worker())
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(text("SELECT status FROM processing_queue WHERE id IN (%s)" %
                                              ",".join(str(i) for i in item_ids)))).all()
            if rows and all(r[0] in ("done", "failed", "skipped") for r in rows):
                break
            await asyncio.sleep(0.05)
    finally:
        q._WORKER_STOP = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        q._WORKER_STOP = False
