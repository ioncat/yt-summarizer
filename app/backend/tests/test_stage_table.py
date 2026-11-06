"""NS-25 step 1: the processing_stages table, its reason codes and the idempotent fill from the old columns."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from models import database as dbm
from models.models import SubtitleFormatted, Video
from services.stage_backfill import backfill_processing_stages
from services.stage_codes import ERROR_CODES, STAGES, STATUSES, classify_error


@pytest_asyncio.fixture(autouse=True)
async def _clean(client):
    async def wipe():
        async with dbm.engine.begin() as conn:
            await conn.execute(text("DELETE FROM processing_stages"))
    await wipe()
    yield
    await wipe()


@pytest_asyncio.fixture
async def make_video(db_session):
    created: list[str] = []

    async def make(video_id, url=None, **fmt):
        for k, val in fmt.items():                      # the ORM wants datetime objects for the time columns
            if k.endswith(("_started_at", "_finished_at")) and isinstance(val, str):
                fmt[k] = datetime.fromisoformat(val)
        v = Video(url=url or f"https://www.youtube.com/watch?v={video_id}", video_id=video_id, title=video_id, duration=60)
        db_session.add(v)
        await db_session.flush()
        db_session.add(SubtitleFormatted(video_id=v.id, language="en", text_length=10, processing_status="success",
                                         formatted_text=fmt.pop("formatted_text", "Some text."), **fmt))
        vid = v.id
        await db_session.commit()
        created.append(vid)
        return SimpleNamespace(id=vid)

    yield make
    for vid in created:
        await db_session.execute(text("DELETE FROM subtitles_formatted WHERE video_id = :v"), {"v": vid})
        await db_session.execute(text("DELETE FROM videos WHERE id = :v"), {"v": vid})
    await db_session.commit()


async def _fill() -> dict:
    async with dbm.engine.begin() as conn:
        return await backfill_processing_stages(conn)


async def _rows(video_id: str, stage: str | None = None) -> list[dict]:
    sql = "SELECT * FROM processing_stages WHERE video_id = :v"
    params = {"v": video_id}
    if stage:
        sql += " AND stage = :s"
        params["s"] = stage
    async with dbm.engine.begin() as conn:
        return [dict(r) for r in (await conn.execute(text(sql + " ORDER BY id"), params)).mappings().all()]


# --- the table --------------------------------------------------------------------------------------

async def test_the_table_and_its_index_exist():
    async with dbm.engine.begin() as conn:
        cols = {r[1]: r for r in (await conn.execute(text("PRAGMA table_info(processing_stages)"))).fetchall()}
        idx = (await conn.execute(text("PRAGMA index_list(processing_stages)"))).fetchall()
    assert set(cols) == {"id", "video_id", "stage", "status", "queue_item_id", "attempt", "model", "started_at",
                         "finished_at", "error_code", "error_text", "meta", "progress_done", "progress_total", "created_at"}
    assert any(i[1] == "ix_processing_stages_video_stage" for i in idx)


def test_the_names_are_the_ones_of_the_plan():
    assert STAGES == ("extract", "transcribe", "cleanup", "summary", "mindmap", "download")     # (download: NS-17 items 12 / 13)
    assert STATUSES == ("processing", "done", "failed", "cancelled")
    assert {"empty_answer", "context_too_small", "model_missing", "timeout", "no_subtitles", "ollama_down",
            "cancelled", "unexpected"} <= set(ERROR_CODES)


@pytest.mark.parametrize("message,code", [
    (None, None), ("", None), ("   ", None),
    ("model returned no answer (thinking used the whole context) — raise llm_max_num_ctx", "empty_answer"),
    ("model returned nothing", "empty_answer"),
    ("No summary was produced: Ollama may be unreachable, or the model returned nothing", "empty_answer"),
    ("No cleaned text was produced: Ollama may be unreachable, or the model returned nothing", "empty_answer"),
    ("Summary needs an Ollama URL and a summarization model: set them in Settings", "model_missing"),
    ("Cleanup needs an Ollama URL and a cleanup model: set them in Settings", "model_missing"),
    ("Mind map: video abc is not in History", "not_found"),
    ("Cleanup: the video has no text to clean", "no_text"),
    ("Summary: the video has no text to summarize", "no_text"),
    ("This video has no subtitles available.", "no_subtitles"),
    ("Mind map did not run: an earlier stage failed (cleanup exploded)", "upstream_failed"),
    ("Summary cancelled", "cancelled"),
    ("Read timed out after 120s", "timeout"),
    ("the answer was cut off (done_reason=length)", "context_too_small"),
    ("Cannot connect to Ollama: connection refused", "ollama_down"),
    ("llm exploded", "unexpected"),
    # the real texts (httpx / Ollama) seen on failed runs
    ("model 'qwen3:8b' not found", "model_missing"),
    ('model "qwen3:8b" not found, try pulling it first', "model_missing"),
    ("Client error '404 Not Found' for url 'http://localhost:11434/api/chat' - model 'x' not found", "model_missing"),
    ("All connection attempts failed", "ollama_down"),
    ("httpx.ConnectError: [WinError 10061] No connection could be made because the target machine actively refused it", "ollama_down"),
    ("Ollama returned HTTP 500", "ollama_down"),
    ("Server error '500 Internal Server Error' for url 'http://localhost:11434/api/chat'", "ollama_down"),
    ("Client error '400 Bad Request' for url 'http://localhost:11434/api/chat'", "unexpected"),
    ("Mind map: video abc is not in History", "not_found"),
    ("input exceeds the context length of the model", "context_too_small"),
])
def test_error_texts_get_a_reason_code(message, code):
    assert classify_error(message) == code


# --- the fill from the old columns ----------------------------------------------------------------------

async def test_a_cleaned_summarized_video_gets_a_done_row_per_stage_with_model_times_and_meta(make_video):
    await make_video("stgFull0001", subtitle_source="captions",
                     cleaned_text="C", cleanup_status="done", cleanup_model="gemma",
                     cleanup_started_at="2026-11-01 10:00:00.000000", cleanup_finished_at="2026-11-01 10:05:00.000000",
                     summary_text="S", summary_status="done", summary_model="qwen", summary_mode="map_reduce",
                     summary_chunks_count=7, summary_started_at="2026-11-01 11:00:00.000000",
                     summary_finished_at="2026-11-01 11:02:00.000000",
                     mindmap_text="# M", mindmap_status="done")
    counts = await _fill()
    assert counts["cleanup"] >= 1 and counts["summary"] >= 1
    (c,) = await _rows("stgFull0001", "cleanup")
    assert (c["status"], c["model"], c["attempt"], c["error_code"]) == ("done", "gemma", 1, None)
    assert str(c["started_at"]).startswith("2026-11-01 10:00") and str(c["finished_at"]).startswith("2026-11-01 10:05")
    (s,) = await _rows("stgFull0001", "summary")
    assert s["model"] == "qwen" and json.loads(s["meta"]) == {"legacy": True, "mode": "map_reduce", "chunks": 7}
    (m,) = await _rows("stgFull0001", "mindmap")
    assert m["status"] == "done"
    (e,) = await _rows("stgFull0001", "extract")
    assert e["status"] == "done" and json.loads(e["meta"]) == {"legacy": True, "source": "captions"}


async def test_a_failed_rerun_on_top_of_a_saved_result_gives_a_done_row_then_a_failed_row(make_video):
    await make_video("stgRerun001", subtitle_source="captions", summary_text="OLD", summary_status="failed",
                     summary_model="new-model", summary_error="model returned nothing",
                     summary_started_at="2026-11-01 11:00:00.000000", summary_finished_at="2026-11-01 11:02:00.000000")
    await _fill()
    rows = await _rows("stgRerun001", "summary")
    assert [(r["status"], r["attempt"]) for r in rows] == [("done", 1), ("failed", 2)]     # the failed one is the newest
    assert rows[1]["error_text"] == "model returned nothing" and rows[1]["error_code"] == "empty_answer"
    assert rows[0]["error_code"] is None


async def test_a_failed_first_run_gives_only_a_failed_row_and_a_status_less_saved_text_gives_a_done_row(make_video):
    await make_video("stgFailed001", subtitle_source="captions", mindmap_status="failed", mindmap_error="boom")
    await make_video("stgNoText001", subtitle_source="captions", summary_status="failed")       # failed, error text lost
    await make_video("stgCancel001", subtitle_source="captions", cleaned_text="KEPT", cleanup_status=None)  # cancelled re-run
    await _fill()
    assert [(r["status"], r["error_code"]) for r in await _rows("stgFailed001", "mindmap")] == [("failed", "unexpected")]
    assert [r["status"] for r in await _rows("stgCancel001", "cleanup")] == ["done"]
    (n,) = await _rows("stgNoText001", "summary")
    assert (n["status"], n["error_text"], n["error_code"]) == ("failed", None, "unexpected")


async def test_nothing_is_copied_for_stages_that_never_ran_or_are_processing(make_video):
    await make_video("stgIdle00001", subtitle_source="captions")
    await make_video("stgBusy00001", subtitle_source="captions", cleanup_status="processing", summary_status="processing")
    await _fill()
    assert [r["stage"] for r in await _rows("stgIdle00001")] == ["extract"]
    assert [r["stage"] for r in await _rows("stgBusy00001")] == ["extract"]          # 'processing' is not copied


async def test_a_speech_to_text_video_gets_a_transcribe_row_with_model_and_device(make_video):
    await make_video("stgStt000001", subtitle_source="transcript", transcription_model="large-v3",
                     transcription_device="cuda", transcription_started_at="2026-11-01 09:00:00.000000",
                     transcription_finished_at="2026-11-01 09:30:00.000000")
    await _fill()
    rows = await _rows("stgStt000001")
    assert [r["stage"] for r in rows] == ["transcribe"]
    assert rows[0]["model"] == "large-v3" and json.loads(rows[0]["meta"])["device"] == "cuda"


async def test_pending_placeholders_are_skipped(make_video):
    await make_video("stgPend00001", url="__pending__stgPend00001", cleaned_text="C", cleanup_status="done")
    await _fill()
    assert await _rows("stgPend00001") == []


async def test_running_it_again_changes_nothing(make_video):
    await make_video("stgTwice0001", subtitle_source="captions", cleaned_text="C", cleanup_status="done",
                     summary_text="S", summary_status="failed", summary_error="x")
    first = await _fill()
    snapshot = await _rows("stgTwice0001")
    second = await _fill()
    assert first and second.get("cleanup", 0) == 0 and second == {k: v for k, v in second.items() if k not in ("cleanup", "summary", "extract")}
    assert await _rows("stgTwice0001") == snapshot


async def test_a_stage_that_already_has_a_row_is_left_alone(make_video):
    """A run recorded by the new code must never be duplicated or overwritten by the legacy fill."""
    await make_video("stgOwned0001", subtitle_source="captions", cleaned_text="C", cleanup_status="done", cleanup_model="old")
    async with dbm.engine.begin() as conn:
        await conn.execute(text("INSERT INTO processing_stages (video_id, stage, status, attempt, model, created_at) "
                                "VALUES ('stgOwned0001', 'cleanup', 'processing', 1, 'new', datetime('now'))"))
    await _fill()
    rows = await _rows("stgOwned0001", "cleanup")
    assert [(r["status"], r["model"]) for r in rows] == [("processing", "new")]
    assert [r["stage"] for r in await _rows("stgOwned0001", "extract")] == ["extract"]    # other stages are still filled


async def test_the_old_columns_are_not_changed_by_the_fill(make_video, db_session):
    v = await make_video("stgKeep00001", subtitle_source="captions", cleaned_text="C", cleanup_status="done",
                         cleanup_model="gemma", summary_status="failed", summary_error="x")
    before = (await db_session.execute(text("SELECT * FROM subtitles_formatted WHERE video_id = :v"), {"v": v.id})).mappings().all()
    await _fill()
    await db_session.rollback()
    after = (await db_session.execute(text("SELECT * FROM subtitles_formatted WHERE video_id = :v"), {"v": v.id})).mappings().all()
    assert [dict(r) for r in before] == [dict(r) for r in after]


async def test_init_db_runs_the_fill_and_survives_a_second_start(make_video):
    await make_video("stgInit00001", subtitle_source="captions", cleaned_text="C", cleanup_status="done")
    await dbm.init_db()
    count = len(await _rows("stgInit00001"))
    assert count >= 2                                           # extract + cleanup
    await dbm.init_db()
    assert len(await _rows("stgInit00001")) == count            # a restart adds nothing


# --- bounded reasons and model names (NS-25 last review) ----------------------------------------------------

def test_a_failure_reason_is_cut_to_500_characters():
    from services.ollama_options import begin_llm_run, llm_failure_reason, record_failure_reason
    begin_llm_run(None)
    record_failure_reason("x" * 5000)
    assert len(llm_failure_reason()) == 500
    record_failure_reason("second reasons are ignored")
    assert llm_failure_reason() == "x" * 500


@pytest.mark.parametrize("stage", ["cleanup", "summarization", "chat"])
async def test_a_model_name_longer_than_200_characters_is_refused(client, stage):
    assert (await client.put(f"/api/settings/{stage}", json={"model": "m" * 200})).status_code == 200
    r = await client.put(f"/api/settings/{stage}", json={"model": "m" * 201})
    assert r.status_code == 422
    assert (await client.get("/api/settings")).json()[stage]["model"] == "m" * 200          # the refused value was not saved
    await client.put(f"/api/settings/{stage}", json={"model": None})


async def test_the_stt_model_setting_has_the_same_limit(client):
    assert (await client.put("/api/settings/app", json={"stt_model": "w" * 201})).status_code == 422
    assert (await client.put("/api/settings/app", json={"stt_model": "base"})).status_code == 200
