"""A short retry for "database is locked", and the 503 answer for when it does not help (NS-28 item 2).

SQLite lets one writer in at a time; when another connection holds the file longer than the busy timeout the
statement fails with "database is locked". For the queue add that used to be a bare 500 after 5 s. Now each step of
the add is tried a few times, and if the file stays locked the client gets 503 "database busy, try again".
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("api")

T = TypeVar("T")
ATTEMPTS = 3
FIRST_DELAY_S = 0.5  # then 1.0 s
# A failure that took this long already waited out SQLite's busy timeout (30 s): trying again would only wait
# another 30 s, so the request answers 503 now. Only quick failures are retried. Worst case for one step: one
# busy-timeout wait (~30 s), never 3 x 30 s.
SLOW_FAILURE_S = 5.0
DEADLINE_S = 35.0  # hard ceiling for one step, retries and pauses included
RETRY_AFTER_S = 5  # what the 503 tells the client; the database has just been locked for a while
BUSY_MESSAGE = "database busy, try again"

_now = time.monotonic


def is_locked(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, OperationalError) and ("database is locked" in text or "database table is locked" in text)


async def retry_locked(operation: Callable[[], Awaitable[T]], db: AsyncSession, what: str = "database step") -> T:
    """Run `operation`; if the database is locked, roll the session back and try again (up to ATTEMPTS times).

    `operation` must be safe to run again: it either completed (committed) or changed nothing.
    A failure that was slow (the busy timeout already ran out) is not retried; see SLOW_FAILURE_S and DEADLINE_S.
    """
    started = _now()
    for attempt in range(1, ATTEMPTS + 1):
        attempt_started = _now()
        try:
            return await operation()
        except OperationalError as exc:
            delay = FIRST_DELAY_S * 2 ** (attempt - 1)
            now = _now()
            if (not is_locked(exc) or attempt == ATTEMPTS
                    or now - attempt_started >= SLOW_FAILURE_S or now - started + delay >= DEADLINE_S):
                raise
            logger.warning("%s: database is locked, retry %d/%d", what, attempt, ATTEMPTS - 1)
            await db.rollback()
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
