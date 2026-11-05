"""A short retry for "database is locked", and the 503 answer for when it does not help (NS-28 item 2).

SQLite lets one writer in at a time; when another connection holds the file longer than the busy timeout the
statement fails with "database is locked". For the queue add that used to be a bare 500 after 5 s. Now each step of
the add is tried a few times, and if the file stays locked the client gets 503 "database busy, try again".
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("api")

T = TypeVar("T")
ATTEMPTS = 3
FIRST_DELAY_S = 0.5  # then 1.0 s
BUSY_MESSAGE = "database busy, try again"


def is_locked(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, OperationalError) and ("database is locked" in text or "database table is locked" in text)


async def retry_locked(operation: Callable[[], Awaitable[T]], db: AsyncSession, what: str = "database step") -> T:
    """Run `operation`; if the database is locked, roll the session back and try again (up to ATTEMPTS times).

    `operation` must be safe to run again: it either completed (committed) or changed nothing.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await operation()
        except OperationalError as exc:
            if not is_locked(exc) or attempt == ATTEMPTS:
                raise
            logger.warning("%s: database is locked, retry %d/%d", what, attempt, ATTEMPTS - 1)
            await db.rollback()
            await asyncio.sleep(FIRST_DELAY_S * 2 ** (attempt - 1))
    raise AssertionError("unreachable")  # pragma: no cover
