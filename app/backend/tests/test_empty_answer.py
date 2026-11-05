"""An empty model answer is its own error (NS-26). The Ollama HTTP calls are mocked with respx."""
import json

import httpx
import pytest
import respx

from services.ollama_options import begin_llm_run, llm_failure_reason
from tests.baseline_helpers import VIDEO_ID, fmt_row, set_fmt

OLLAMA = "http://localhost:11434"
TAGS = f"{OLLAMA}/api/tags"
CHAT = f"{OLLAMA}/api/chat"
THINKING_MSG = ("model returned no answer (thinking used the whole context) — "
                "use a model without thinking (or raise llm_max_num_ctx if the input is very long)")
NOTHING_MSG = "model returned nothing"


def _chat_answer(content="", thinking=None):
    msg = {"role": "assistant", "content": content}
    if thinking is not None:
        msg["thinking"] = thinking
    return httpx.Response(200, json={"message": msg, "done": True, "done_reason": "length" if not content else "stop"})


@pytest.fixture(autouse=True)
async def _setup(client):
    await client.put("/api/settings/summarization", json={"model": "m"})
    await client.put("/api/settings/app", json={"ollama_url": OLLAMA})
    yield


# --- the LLM functions -------------------------------------------------------

@respx.mock
async def test_summary_empty_content_with_thinking_gives_the_thinking_message():
    begin_llm_run(None)  # the reason box lives in the test task's context
    from services.text_summarizer import summarize_text
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer("", thinking="let me think about this..."))
    result, mode, _ = await summarize_text("Некоторый текст.", model="m", ollama_url=OLLAMA)
    assert result is None
    assert llm_failure_reason() == THINKING_MSG


@respx.mock
async def test_summary_empty_content_without_thinking_gives_the_nothing_message():
    begin_llm_run(None)  # the reason box lives in the test task's context
    from services.text_summarizer import summarize_text
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer(""))
    assert (await summarize_text("Некоторый текст.", model="m", ollama_url=OLLAMA))[0] is None
    assert llm_failure_reason() == NOTHING_MSG


@respx.mock
async def test_summary_normal_answer_is_unchanged_and_records_no_reason():
    begin_llm_run(None)  # the reason box lives in the test task's context
    from services.text_summarizer import summarize_text
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer("Сводка текста.", thinking="short thought"))
    result, mode, count = await summarize_text("Некоторый текст.", model="m", ollama_url=OLLAMA)
    assert result == "Сводка текста." and mode == "single" and count == 1
    assert llm_failure_reason() is None


@respx.mock
async def test_reason_is_kept_when_a_map_reduce_chunk_fails():
    begin_llm_run(None)  # the reason box lives in the test task's context
    from services.text_summarizer import summarize_text
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer("", thinking="x"))
    result, mode, _ = await summarize_text("word " * 6000, model="m", ollama_url=OLLAMA, force_map_reduce=True)
    assert result is None and mode == "map_reduce"
    assert llm_failure_reason() == THINKING_MSG


@respx.mock
@pytest.mark.parametrize("thinking_chunk,expected", [(True, THINKING_MSG), (False, NOTHING_MSG)])
async def test_mindmap_stream_empty_content_reason(thinking_chunk, expected):
    begin_llm_run(None)  # the reason box lives in the test task's context
    from services.text_mindmapper import generate_mindmap
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    lines = []
    if thinking_chunk:
        lines.append(json.dumps({"message": {"content": "", "thinking": "hmm"}, "done": False}))
    lines.append(json.dumps({"message": {"content": ""}, "done": True, "done_reason": "length"}))
    respx.post(CHAT).mock(return_value=httpx.Response(200, content=("\n".join(lines) + "\n").encode()))
    assert await generate_mindmap("Текст.", OLLAMA, "m", "Russian") is None
    assert llm_failure_reason() == expected


@respx.mock
async def test_mindmap_normal_stream_is_unchanged():
    begin_llm_run(None)  # the reason box lives in the test task's context
    from services.text_mindmapper import generate_mindmap
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    body = json.dumps({"message": {"content": "# Root"}, "done": True}) + "\n"
    respx.post(CHAT).mock(return_value=httpx.Response(200, content=body.encode()))
    assert await generate_mindmap("Текст.", OLLAMA, "m", "Russian") == "# Root"
    assert llm_failure_reason() is None


def _cleanup_text(n):
    return "\n\n".join(f"Исходный абзац номер {i}." for i in range(n))


def _all_empty(request):
    return _chat_answer("", thinking="x")


def _answers(empty_indexes, thinking=True):
    """Ollama fake: the paragraph whose text contains 'номер i' for i in empty_indexes gets an empty answer."""
    def handler(request):
        user = json.loads(request.content)["messages"][-1]["content"]
        if any(f"номер {i}." in user for i in empty_indexes):
            return _chat_answer("", thinking="x" if thinking else None)
        return _chat_answer("Очищенный абзац.")
    return handler


@respx.mock
async def test_cleanup_a_few_empty_answers_keep_the_original_paragraph_and_succeed():
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_answers({1}))
    out = await clean_text(_cleanup_text(5), model="m", ollama_url=OLLAMA)
    assert out is not None
    paragraphs = out.split("\n\n")
    assert "Исходный абзац номер 1." in paragraphs and paragraphs.count("Очищенный абзац.") == 4
    assert llm_failure_reason() is None


@respx.mock
async def test_cleanup_half_empty_is_still_not_a_failure():
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_answers({0, 1}))  # exactly half of 4
    assert await clean_text(_cleanup_text(4), model="m", ollama_url=OLLAMA) is not None
    assert llm_failure_reason() is None


@respx.mock
@pytest.mark.parametrize("n,empty", [(5, {0, 1, 2}), (2, {0, 1}), (1, {0})])
async def test_cleanup_most_or_all_empty_answers_fail_with_the_specific_reason(n, empty):
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_answers(empty))
    assert await clean_text(_cleanup_text(n), model="m", ollama_url=OLLAMA) is None
    assert llm_failure_reason() == THINKING_MSG


@respx.mock
async def test_cleanup_all_empty_without_thinking_says_nothing_returned():
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_answers({0}, thinking=False))
    assert await clean_text(_cleanup_text(1), model="m", ollama_url=OLLAMA) is None
    assert llm_failure_reason() == NOTHING_MSG


@respx.mock
async def test_cleanup_run_stores_the_reason_and_the_result_exposes_it(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_all_empty)
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and row["cleanup_error"] == THINKING_MSG
    assert (await client.get(f"/api/result/{VIDEO_ID}")).json()["cleanup_error"] == THINKING_MSG


@respx.mock
async def test_a_successful_second_cleanup_clears_cleanup_error(client, seeded_video):
    await client.put("/api/settings/cleanup", json={"model": "m"})
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    route = respx.post(CHAT).mock(side_effect=_all_empty)
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    assert (await fmt_row())["cleanup_error"] == THINKING_MSG
    route.mock(return_value=_chat_answer("Очищенный абзац."))
    await client.post(f"/api/result/{VIDEO_ID}/cleanup")
    row = await fmt_row()
    assert row["cleanup_status"] == "done" and row["cleanup_error"] is None
    assert (await client.get(f"/api/result/{VIDEO_ID}")).json()["cleanup_error"] is None


@respx.mock
async def test_truncated_cleanup_paragraph_is_logged_but_still_used(monkeypatch):
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=httpx.Response(200, json={
        "message": {"role": "assistant", "content": "Half a paragr"}, "done": True, "done_reason": "length"}))
    logged = _collect_warnings(monkeypatch, "services.text_cleaner")
    out = await clean_text("Исходный абзац.", model="m", ollama_url=OLLAMA)
    assert out == "Half a paragr" and llm_failure_reason() is None
    assert any("cut" in m and "done_reason=length" in m for m in logged)


@respx.mock
async def test_queue_cleanup_stage_stores_the_reason(seeded_video):
    from services import queue_service as q
    await set_fmt(cleanup_status=None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_all_empty)
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put("/api/settings/cleanup", json={"model": "m"})
    await q._run_cleanup_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and row["cleanup_error"] == THINKING_MSG


def _collect_warnings(monkeypatch, module):
    logged = []
    monkeypatch.setattr(f"{module}.logger.warning", lambda msg, *a, **k: logged.append(msg % a if a else msg))
    return logged


# --- a non-empty answer that was cut off is only logged -----------------------

@respx.mock
async def test_truncated_answer_is_logged_but_still_used(monkeypatch):
    from services.text_summarizer import summarize_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=httpx.Response(200, json={
        "message": {"role": "assistant", "content": "Half a summ"}, "done": True, "done_reason": "length"}))
    logged = _collect_warnings(monkeypatch, "services.text_summarizer")
    result, mode, _ = await summarize_text("Текст.", model="m", ollama_url=OLLAMA)
    assert result == "Half a summ" and llm_failure_reason() is None
    assert any("cut off" in m and "llm_max_num_ctx" in m for m in logged)


@respx.mock
async def test_truncated_mindmap_is_logged_but_still_used(monkeypatch):
    from services.text_mindmapper import generate_mindmap
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    body = json.dumps({"message": {"content": "# Root"}, "done": True, "done_reason": "length"}) + "\n"
    respx.post(CHAT).mock(return_value=httpx.Response(200, content=body.encode()))
    logged = _collect_warnings(monkeypatch, "services.text_mindmapper")
    assert await generate_mindmap("Текст.", OLLAMA, "m", "Russian") == "# Root"
    assert any("cut off" in m for m in logged)


# --- stored on the result and shown by the API -------------------------------

@respx.mock
async def test_summary_run_stores_the_reason_and_the_result_exposes_it(client, seeded_video):
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer("", thinking="x"))
    await client.post(f"/api/result/{VIDEO_ID}/summary")
    row = await fmt_row()
    assert row["summary_status"] == "failed" and row["summary_error"] == THINKING_MSG
    data = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert data["summary_error"] == THINKING_MSG and data["mindmap_error"] is None and data["cleanup_error"] is None


@respx.mock
async def test_mindmap_run_stores_the_reason(client, seeded_video):
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=httpx.Response(
        200, content=(json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode()))
    await client.post(f"/api/result/{VIDEO_ID}/mindmap")
    row = await fmt_row()
    assert row["mindmap_status"] == "failed" and row["mindmap_error"] == NOTHING_MSG


@respx.mock
async def test_a_successful_rerun_clears_the_old_reason(client, seeded_video):
    await set_fmt(summary_status="failed", summary_error=THINKING_MSG)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer("Готовая сводка."))
    await client.post(f"/api/result/{VIDEO_ID}/summary")
    row = await fmt_row()
    assert row["summary_status"] == "done" and row["summary_error"] is None


@respx.mock
async def test_unreachable_ollama_leaves_no_specific_reason(client, seeded_video):
    respx.get(TAGS).mock(side_effect=httpx.ConnectError("refused"))
    await client.post(f"/api/result/{VIDEO_ID}/summary")
    row = await fmt_row()
    assert row["summary_status"] == "failed" and row["summary_error"] is None  # page keeps its generic text


@respx.mock
async def test_queue_summary_stage_stores_the_reason(seeded_video):
    from services import queue_service as q
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer("", thinking="x"))
    await q._run_summary_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["summary_status"] == "failed" and row["summary_error"] == THINKING_MSG


async def test_queue_stage_exception_text_is_stored(seeded_video):
    from unittest.mock import patch
    from services import queue_service as q

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    with patch("services.text_summarizer.summarize_text", boom):
        with pytest.raises(RuntimeError):
            await q._run_summary_stage(VIDEO_ID, 1)
    assert (await fmt_row())["summary_error"] == "llm exploded"
