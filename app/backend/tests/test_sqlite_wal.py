"""NS-28 item 1: WAL, a 30 s busy timeout and synchronous=NORMAL on every connection; the backup tool that goes with WAL."""
import asyncio
import importlib.util
import os
import shutil
import sqlite3
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from models import database as dbm

TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools", "backup_db.py")


def _url(path) -> str:
    return f"sqlite+aiosqlite:///{path}"


async def _pragmas(engine) -> dict:
    async with engine.connect() as conn:
        return {
            "journal_mode": (await conn.execute(text("PRAGMA journal_mode"))).scalar(),
            "busy_timeout": (await conn.execute(text("PRAGMA busy_timeout"))).scalar(),
            "synchronous": (await conn.execute(text("PRAGMA synchronous"))).scalar(),
        }


async def _make_table(engine):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)"))
        # a few rows, so that a reader that fetches one row leaves its cursor (and its lock) open
        if (await conn.execute(text("SELECT COUNT(*) FROM t"))).scalar() == 0:
            for i in range(5):
                await conn.execute(text("INSERT INTO t (v) VALUES (:v)"), {"v": f"seed {i}"})


async def _insert(engine, value="x") -> float:
    t = time.perf_counter()
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO t (v) VALUES (:v)"), {"v": value})
    return time.perf_counter() - t


def _hold(path, kind, seconds, ready):
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=1)
    if kind == "write":
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO t (v) VALUES ('held')")
    else:  # read lock: a SELECT whose cursor is not finished
        cursor = conn.execute("SELECT * FROM t")  # keep the cursor: a finished/closed statement releases its lock
        cursor.fetchone()
    ready.set()
    time.sleep(seconds)
    if kind == "write":
        conn.execute("ROLLBACK")
    conn.close()


async def _insert_while_held(engine, path, kind, seconds) -> float:
    ready = threading.Event()
    thread = threading.Thread(target=_hold, args=(path, kind, seconds, ready))
    thread.start()
    ready.wait()
    try:
        return await _insert(engine, "while-held")
    finally:
        await asyncio.to_thread(thread.join)


# --- the settings ---------------------------------------------------------------------

async def test_every_connection_runs_wal_busy_timeout_30s_and_synchronous_normal(tmp_path):
    engine = dbm.create_engine_for(_url(tmp_path / "a.sqlite"))
    try:
        assert await _pragmas(engine) == {"journal_mode": "wal", "busy_timeout": 30000, "synchronous": 1}
    finally:
        await engine.dispose()


async def test_the_step_is_idempotent_and_the_file_stays_wal_after_a_restart(tmp_path):
    path = tmp_path / "b.sqlite"
    for _ in range(3):  # three "starts" of the app against the same file
        engine = dbm.create_engine_for(_url(path))
        try:
            assert (await _pragmas(engine))["journal_mode"] == "wal"
            await _make_table(engine)
        finally:
            await engine.dispose()
    # the mode is stored in the file: a plain connection sees WAL without setting anything
    assert sqlite3.connect(str(path)).execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert (tmp_path / "b.sqlite").exists()


async def test_a_database_that_is_still_in_the_old_mode_is_converted_on_first_start(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(str(path))
    old.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    old.execute("INSERT INTO t (v) VALUES ('kept')")
    old.commit()
    assert old.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    old.close()
    engine = dbm.create_engine_for(_url(path))
    try:
        assert (await _pragmas(engine))["journal_mode"] == "wal"
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT v FROM t"))).scalar() == "kept"  # data intact
    finally:
        await engine.dispose()


def test_a_failing_pragma_is_logged_and_the_others_still_run(caplog, monkeypatch):
    seen, warnings = [], []

    class Cursor:
        def execute(self, sql):
            seen.append(sql)
            if "journal_mode" in sql:
                raise sqlite3.OperationalError("database is locked")

        def fetchall(self):
            return []

        def close(self):
            seen.append("closed")

    class Conn:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr(dbm.logger, "warning", lambda msg, *a: warnings.append(msg % a))
    dbm._apply_sqlite_pragmas(Conn())
    assert seen == ["PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=30000", "PRAGMA synchronous=NORMAL", "closed"]
    assert len(warnings) == 1 and "journal_mode=WAL failed" in warnings[0]


# --- held locks (the NS-28 experiment as tests) -------------------------------------------

async def test_a_reader_no_longer_blocks_an_insert_in_wal_but_did_before(tmp_path):
    old_path, new_path = tmp_path / "old.sqlite", tmp_path / "new.sqlite"
    old = create_async_engine(_url(old_path), connect_args={"timeout": 30})  # the previous setup: rollback journal
    new = dbm.create_engine_for(_url(new_path))
    try:
        for e in (old, new):
            await _make_table(e)
        assert await _insert_while_held(old, old_path, "read", 1.2) >= 1.0   # waited for the reader
        assert await _insert_while_held(new, new_path, "read", 1.2) < 0.5    # WAL: no waiting
    finally:
        await old.dispose()
        await new.dispose()


async def test_a_writer_waits_for_another_writer_and_then_succeeds(tmp_path):
    path = tmp_path / "w.sqlite"
    engine = dbm.create_engine_for(_url(path))
    try:
        await _make_table(engine)
        waited = await _insert_while_held(engine, path, "write", 1.2)
        assert 1.0 <= waited < 5.0
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT COUNT(*) FROM t WHERE v = 'while-held'"))).scalar() == 1
    finally:
        await engine.dispose()


async def test_a_write_lock_longer_than_the_old_5_s_limit_no_longer_fails(tmp_path):
    """Before: HTTP 500 after 5.8 s when another connection held a write lock for 7 s (NS-28 measurement)."""
    path = tmp_path / "long.sqlite"
    engine = dbm.create_engine_for(_url(path))
    try:
        await _make_table(engine)
        waited = await _insert_while_held(engine, path, "write", 6.5)
        assert waited >= 6.0  # it waited past the old 5 s limit and still completed
    finally:
        await engine.dispose()


# --- the backup tool -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def backup_tool():
    spec = importlib.util.spec_from_file_location("backup_db_tool", TOOLS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wal_database_with_rows(path, rows=200):
    """A WAL database whose newest commits are still in the -wal file (another connection keeps it open)."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")  # never fold the WAL into the main file on its own
    conn.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO videos (v) VALUES (?)", (f"row {i}",))
    return conn


def test_a_plain_file_copy_misses_wal_data_and_the_backup_tool_does_not(tmp_path, backup_tool):
    db = tmp_path / "live.sqlite"
    holder = _wal_database_with_rows(db)
    try:
        assert os.path.exists(str(db) + "-wal") and os.path.getsize(str(db) + "-wal") > 0
        plain = tmp_path / "plain-copy.sqlite"
        shutil.copy(db, plain)
        try:
            plain_rows = sqlite3.connect(str(plain)).execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        except sqlite3.OperationalError:
            plain_rows = 0  # not even the table is in the main file yet
        assert plain_rows < 200  # a copy of only the .sqlite file is not a backup

        target = backup_tool.backup(str(db), str(tmp_path / "backups"), label="before wal!")
        assert os.path.basename(target).startswith("live-before-wal--")  # label made safe for a file name
        got = sqlite3.connect(target)
        assert got.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 200
        assert got.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        got.close()
        assert not os.path.exists(target + "-wal") and not os.path.exists(target + "-shm")
        assert backup_tool.counts(target)["videos"] == 200
    finally:
        holder.close()


def test_the_backup_tool_does_not_change_the_live_database(tmp_path, backup_tool):
    db = tmp_path / "live.sqlite"
    holder = _wal_database_with_rows(db, rows=5)
    try:
        before = holder.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        backup_tool.backup(str(db), str(tmp_path / "b"))
        assert holder.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == before
        assert holder.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        holder.close()


def test_the_backup_tool_refuses_a_missing_database(tmp_path, backup_tool):
    with pytest.raises(FileNotFoundError):
        backup_tool.backup(str(tmp_path / "nope.sqlite"), str(tmp_path / "b"))
    assert not (tmp_path / "b").exists() or os.listdir(tmp_path / "b") == []


def test_the_wal_side_files_are_git_ignored():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    ignore = open(os.path.join(root, ".gitignore"), encoding="utf-8").read().splitlines()
    for pattern in ("app/data/db/", "*.sqlite-wal", "*.sqlite-shm", "*.db-wal", "*.db-shm"):
        assert pattern in ignore, pattern
