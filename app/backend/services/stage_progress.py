"""Live progress counters of a running stage, kept on its `processing_stages` row (NS-25 / NS-11 stage 4b).

A cleanup counts paragraphs, a summary chunks (or chapters). The stage's progress callback is a plain function called from
the event loop, often many times a second (parallel workers); the database must not see every call. `ProgressWriter`
keeps only the latest value and writes it at most once per `min_interval` seconds, in its own short session, and a final
write at `close()`. A failed write is logged and ignored: progress is only a display, it must never fail the stage.
The counters live on the OPEN row only (`set_progress` touches status 'processing' rows); finish / fail / cancel keep the last
values on the row.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import text

logger = logging.getLogger("api")

MIN_INTERVAL_S = 1.0


async def set_progress(video_id: str, stage: str, done: int, total: int, unit: str | None = None,
                       extra: dict | None = None) -> bool:
    """Write the counters of the open run of `stage`, and into its meta the unit word (e.g. "chapter") and any `extra` keys
    (e.g. {"segments": 12}). One short session. Returns True if a row was updated."""
    import json
    from models.database import AsyncSessionLocal
    patch = {**({"unit": unit} if unit else {}), **(extra or {})}
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("UPDATE processing_stages SET progress_done = :done, progress_total = :total, "
                 "meta = CASE WHEN :patch = '{}' THEN meta ELSE json_patch(COALESCE(meta, '{}'), :patch) END "
                 "WHERE video_id = :v AND stage = :s AND status = 'processing'"),
            {"done": done, "total": total, "patch": json.dumps(patch), "v": video_id, "s": stage},
        )
        await db.commit()
        return res.rowcount == 1


class ProgressWriter:
    """Throttled writer of one run's counters. Use inside the running event loop: `update()` is the stage's progress callback."""

    def __init__(self, video_id: str, stage: str, unit: str | None = None, min_interval: float = MIN_INTERVAL_S):
        self.video_id, self.stage, self.unit, self.min_interval = video_id, stage, unit, min_interval
        self._latest: tuple[int, int] | None = None
        self._extra: dict | None = None
        self._written: tuple[int, int] | None = None
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()   # created inside the loop that writes
        except RuntimeError:
            self._loop = None
        self._last_write = 0.0
        self._timer: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def update(self, done: int, total: int, extra: dict | None = None) -> None:
        """The progress callback; `extra` goes into the run's meta. Never blocks and never raises. May be called from another
        thread (the speech-to-text engines run in a worker thread): it then hands over to the writer's own loop."""
        if self._closed:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            if self._loop is not None and not self._loop.is_closed():
                try:
                    self._loop.call_soon_threadsafe(self._update_in_loop, done, total, extra)
                except RuntimeError:
                    pass                                # the loop is gone: progress is only a display
            return
        self._update_in_loop(done, total, extra)

    def _update_in_loop(self, done: int, total: int, extra: dict | None) -> None:
        if self._closed:
            return
        self._latest = (done, total)
        self._extra = extra
        if self._timer is not None:
            return                                     # a write is already scheduled: it will take the latest value
        loop = asyncio.get_running_loop()
        wait = max(0.0, self._last_write + self.min_interval - time.monotonic())
        self._timer = loop.call_later(wait, self._start_flush, loop)

    def _start_flush(self, loop: asyncio.AbstractEventLoop) -> None:
        self._timer = None
        task = loop.create_task(self._flush())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _flush(self) -> None:
        latest = self._latest
        if latest is None or latest == self._written or self._closed:
            return
        self._last_write = time.monotonic()
        try:
            await set_progress(self.video_id, self.stage, latest[0], latest[1], self.unit, self._extra)
            self._written = latest
        except Exception:  # noqa: BLE001 - a locked or busy database must not fail the stage
            logger.warning("progress of %s %s could not be written", self.stage, self.video_id, exc_info=True)

    async def close(self) -> None:
        """No more writes after this: cancel the timer, wait for a write in flight, write the last value once."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        await self._flush()
        self._closed = True
