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


async def set_progress(video_id: str, stage: str, done: int, total: int, unit: str | None = None) -> bool:
    """Write the counters (and the unit word, e.g. "chapter") of the open run of `stage`. One short session. Returns
    True if a row was updated."""
    from models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("UPDATE processing_stages SET progress_done = :done, progress_total = :total, "
                 "meta = CASE WHEN :unit IS NULL THEN meta ELSE json_set(COALESCE(meta, '{}'), '$.unit', :unit) END "
                 "WHERE video_id = :v AND stage = :s AND status = 'processing'"),
            {"done": done, "total": total, "unit": unit, "v": video_id, "s": stage},
        )
        await db.commit()
        return res.rowcount == 1


class ProgressWriter:
    """Throttled writer of one run's counters. Use inside the running event loop: `update()` is the stage's progress callback."""

    def __init__(self, video_id: str, stage: str, unit: str | None = None, min_interval: float = MIN_INTERVAL_S):
        self.video_id, self.stage, self.unit, self.min_interval = video_id, stage, unit, min_interval
        self._latest: tuple[int, int] | None = None
        self._written: tuple[int, int] | None = None
        self._last_write = 0.0
        self._timer: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def update(self, done: int, total: int) -> None:
        """The progress callback. Never blocks and never raises."""
        if self._closed:
            return
        self._latest = (done, total)
        if self._timer is not None:
            return                                     # a write is already scheduled: it will take the latest value
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                                     # no loop (a sync caller): progress is only a display
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
            await set_progress(self.video_id, self.stage, latest[0], latest[1], self.unit)
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
