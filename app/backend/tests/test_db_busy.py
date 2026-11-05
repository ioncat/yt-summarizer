"""NS-28 item 2: a locked database is retried a few times, then answered with 503 "database busy, try again"."""
import sqlite3

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.exc import OperationalError

import main
from services import db_retry
from services.db_retry import (
    ATTEMPTS, BUSY_MESSAGE, DEADLINE_S, FIRST_DELAY_S, RETRY_AFTER_S, SLOW_FAILURE_S, is_locked, retry_locked,
)


def locked(msg="database is locked"):
    return OperationalError("INSERT ...", {}, sqlite3.OperationalError(msg))


class FakeDb:
    def __init__(self):
        self.rollbacks = 0

    async def rollback(self):
        self.rollbacks += 1


CLOCK = {"t": 0.0}  # a fake clock: the pauses and the time an operation "takes" advance it


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []
    CLOCK["t"] = 0.0

    async def fake_sleep(s):
        slept.append(s)
        CLOCK["t"] += s

    monkeypatch.setattr(db_retry.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(db_retry, "_now", lambda: CLOCK["t"])
    return slept


def test_which_errors_count_as_locked():
    assert is_locked(locked()) and is_locked(locked("database table is locked"))
    assert not is_locked(locked("no such table: x"))
    assert not is_locked(RuntimeError("database is locked"))  # only a database error


async def test_retry_succeeds_after_two_locked_attempts_and_rolls_back_in_between(no_sleep):
    db, calls = FakeDb(), []

    async def op():
        calls.append(1)
        if len(calls) < 3:
            raise locked()
        return "done"

    assert await retry_locked(op, db) == "done"
    assert len(calls) == 3 and db.rollbacks == 2 and no_sleep == [0.5, 1.0]


async def test_retry_gives_up_after_three_attempts_with_the_original_error():
    db, calls = FakeDb(), []

    async def op():
        calls.append(1)
        raise locked()

    with pytest.raises(OperationalError):
        await retry_locked(op, db)
    assert len(calls) == 3


async def test_other_errors_are_not_retried():
    db, calls = FakeDb(), []

    async def op():
        calls.append(1)
        raise locked("no such table: x")

    with pytest.raises(OperationalError):
        await retry_locked(op, db)
    assert len(calls) == 1 and db.rollbacks == 0


# --- the worst case is one busy-timeout wait, not three -----------------------------------------

def failing_after(seconds, calls):
    async def op():
        calls.append(1)
        CLOCK["t"] += seconds  # the time SQLite waited for the lock before giving up
        raise locked()
    return op


async def test_a_slow_failure_is_not_retried_because_the_busy_timeout_already_ran_out(no_sleep):
    calls = []
    with pytest.raises(OperationalError):
        await retry_locked(failing_after(30, calls), FakeDb())
    assert len(calls) == 1 and no_sleep == [] and CLOCK["t"] == 30  # one 30 s wait, not 3 x 30 s


async def test_a_failure_at_the_slow_threshold_is_not_retried_but_just_under_it_is(no_sleep):
    calls = []
    with pytest.raises(OperationalError):
        await retry_locked(failing_after(SLOW_FAILURE_S, calls), FakeDb())
    assert len(calls) == 1
    calls.clear()
    CLOCK["t"] = 0.0
    with pytest.raises(OperationalError):
        await retry_locked(failing_after(SLOW_FAILURE_S - 0.1, calls), FakeDb())
    assert len(calls) == ATTEMPTS and CLOCK["t"] < DEADLINE_S


@pytest.mark.parametrize("seconds", [0, 1, 4.9, 5, 10, 30])
async def test_one_step_never_takes_longer_than_the_deadline_whatever_the_lock_wait(seconds):
    with pytest.raises(OperationalError):
        await retry_locked(failing_after(seconds, []), FakeDb())
    assert CLOCK["t"] <= DEADLINE_S  # about 35 s at most (the old worst case was about 90 s)


async def test_the_deadline_also_stops_retries_when_every_failure_is_just_quick_enough(monkeypatch):
    monkeypatch.setattr(db_retry, "SLOW_FAILURE_S", 100.0)  # take the slow rule out: only the deadline is left
    calls = []
    with pytest.raises(OperationalError):
        await retry_locked(failing_after(20, calls), FakeDb())
    assert len(calls) == 2  # 20 s -> retry (20.5 < 35); 40.5 s -> over the deadline, give up


def test_the_numbers_fit_together():
    assert FIRST_DELAY_S + 2 * FIRST_DELAY_S < SLOW_FAILURE_S < DEADLINE_S
    assert RETRY_AFTER_S >= 1


# --- the queue add endpoint -----------------------------------------------------------

URL = "https://www.youtube.com/watch?v=busyAdd0001"


async def test_the_add_survives_a_short_lock(client, monkeypatch):
    from services import queue_service
    real, state = queue_service.add_items_unique, {"calls": 0}

    async def flaky(*a, **k):
        state["calls"] += 1
        if state["calls"] == 1:
            raise locked()
        return await real(*a, **k)

    monkeypatch.setattr(queue_service, "add_items_unique", flaky)
    r = await client.post("/api/queue/bulk", json={"urls": [URL], "pipeline_stages": ["cleanup"]})
    assert r.status_code == 200 and r.json()["added"] == 1 and state["calls"] == 2
    items = (await client.get("/api/queue")).json()["items"]
    assert [i["video_id"] for i in items].count("busyAdd0001") == 1  # added once, not twice
    await client.delete("/api/queue/all")


async def test_a_lock_that_stays_gives_503_database_busy_and_adds_nothing(client, monkeypatch):
    from services import queue_service

    async def always_locked(*a, **k):
        raise locked()

    monkeypatch.setattr(queue_service, "add_items_unique", always_locked)
    r = await client.post("/api/queue/bulk", json={"urls": [URL], "pipeline_stages": ["cleanup"]})
    assert r.status_code == 503 and r.json() == {"detail": BUSY_MESSAGE} and r.headers["retry-after"] == str(RETRY_AFTER_S)
    assert (await client.get("/api/queue")).json()["items"] == []


async def test_a_lock_on_the_by_id_insert_is_handled_the_same_way(client, monkeypatch):
    from services import queue_by_id
    state = {"calls": 0}

    async def always_locked(*a, **k):
        state["calls"] += 1
        raise locked()

    monkeypatch.setattr(queue_by_id, "add_by_video_ids", always_locked)
    r = await client.post("/api/queue/bulk", json={"video_ids": ["file-x"], "pipeline_stages": ["cleanup"]})
    assert r.status_code == 503 and state["calls"] == 3


# --- every other endpoint: the global handler ----------------------------------------------

@pytest.fixture
def db_routes():
    async def locked_route():
        raise locked()

    async def broken_route():
        raise locked("no such table: nothing")

    main.app.add_api_route("/api/_test_locked", locked_route)
    main.app.add_api_route("/api/_test_dberror", broken_route)
    yield
    main.app.router.routes[:] = [r for r in main.app.router.routes
                                 if getattr(r, "path", "") not in ("/api/_test_locked", "/api/_test_dberror")]


async def test_any_endpoint_answers_a_locked_database_with_503(db_routes, init_database):
    async with httpx.AsyncClient(transport=ASGITransport(app=main.app, raise_app_exceptions=False),
                                 base_url="http://test") as c:
        locked_r = await c.get("/api/_test_locked")
        other_r = await c.get("/api/_test_dberror")
    assert locked_r.status_code == 503 and locked_r.json() == {"detail": BUSY_MESSAGE}
    assert other_r.status_code == 500 and other_r.json() == {"detail": "Internal Server Error"}  # not a lock: a crash
    log = open(main._log_file, encoding="utf-8").read()
    assert "database is locked: GET /api/_test_locked -> 503" in log
    assert "unhandled error in GET /api/_test_dberror" in log
