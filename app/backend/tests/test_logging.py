"""backend.log: unhandled request errors are written to it, and the test suite never writes to the live one."""
import logging
import os

import httpx
import pytest
from httpx import ASGITransport

import main

LIVE_LOG = os.path.abspath(os.path.join(os.path.dirname(main.__file__), "..", "..", "data", "logs", "backend.log"))


def test_the_suite_logs_into_a_temp_folder_not_the_live_log():
    assert os.path.abspath(main._log_file) != LIVE_LOG
    assert os.path.abspath(main._log_file).startswith(os.path.abspath(os.environ["YT_SUMMARIZER_LOG_DIR"]))


def test_logging_from_the_app_does_not_touch_the_live_log():
    before = os.stat(LIVE_LOG) if os.path.exists(LIVE_LOG) else None
    logging.getLogger("api").warning("test_logging: this line must not reach the live log")
    logging.getLogger("queue_service").error("test_logging: nor this one")
    after = os.stat(LIVE_LOG) if os.path.exists(LIVE_LOG) else None
    assert (before and before.st_size) == (after and after.st_size)
    assert "this line must not reach" in open(main._log_file, encoding="utf-8").read()


@pytest.fixture
def boom_route():
    async def boom():
        raise RuntimeError("boom from the test route")

    main.app.add_api_route("/api/_test_boom", boom)
    yield
    main.app.router.routes[:] = [r for r in main.app.router.routes if getattr(r, "path", "") != "/api/_test_boom"]


async def test_an_unhandled_exception_is_answered_with_500_and_logged_with_its_traceback(boom_route, init_database):
    async with httpx.AsyncClient(transport=ASGITransport(app=main.app, raise_app_exceptions=False),
                                 base_url="http://test") as c:
        r = await c.get("/api/_test_boom")
    assert r.status_code == 500 and r.json() == {"detail": "Internal Server Error"}
    text = open(main._log_file, encoding="utf-8").read()
    assert "unhandled error in GET /api/_test_boom" in text
    assert "RuntimeError: boom from the test route" in text and "Traceback" in text
