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
THINKING_MSG = "model returned no answer (thinking used the whole context)"
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


@respx.mock
async def test_cleanup_empty_paragraph_answer_still_keeps_the_original_text():
    from services.text_cleaner import clean_text
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=_chat_answer("", thinking="x"))
    out = await clean_text("Исходный абзац.", model="m", ollama_url=OLLAMA)
    assert out == "Исходный абзац."


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
