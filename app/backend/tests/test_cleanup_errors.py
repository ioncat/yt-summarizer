"""Cleanup when the model calls RAISE (a missing model, a server error): more than half of the paragraphs failing is a failed
stage with the real reason, not a silent "done" with the raw text. Empty answers have their own tests in test_empty_answer.py."""
import json

import httpx
import pytest
import respx

from services.ollama_options import begin_llm_run, llm_failure_reason
from tests.baseline_helpers import VIDEO_ID, fmt_row, set_fmt

OLLAMA = "http://localhost:11434"
TAGS = f"{OLLAMA}/api/tags"
CHAT = f"{OLLAMA}/api/chat"
MISSING = "Model 'm' not found in Ollama"


def _text(n):
    return "\n\n".join(f"Исходный абзац номер {i}." for i in range(n))


def _server_errors(bad_indexes):
    """Ollama fake: the paragraph 'номер i' for i in bad_indexes gets HTTP 500, the others a cleaned text."""
    def handler(request):
        user = json.loads(request.content)["messages"][-1]["content"]
        if any(f"номер {i}." in user for i in bad_indexes):
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Очищенный абзац."}, "done": True})
    return handler


@respx.mock
@pytest.mark.parametrize("n", [1, 2, 5])
async def test_a_missing_model_fails_the_cleanup_with_the_real_reason(n):
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=httpx.Response(404, json={"error": "model 'm' not found"}))
    assert await clean_text(_text(n), model="m", ollama_url=OLLAMA) is None
    assert llm_failure_reason() == MISSING


@respx.mock
@pytest.mark.parametrize("n,bad", [(5, {0, 1, 2}), (2, {0, 1}), (1, {0})])
async def test_most_paragraphs_failing_with_server_errors_fails_the_cleanup(n, bad):
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_server_errors(bad))
    assert await clean_text(_text(n), model="m", ollama_url=OLLAMA) is None
    assert llm_failure_reason() is None                  # nothing specific to say; the stage adds its generic message


@respx.mock
async def test_a_few_failed_paragraphs_keep_their_original_text_and_the_cleanup_succeeds():
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_server_errors({1}))
    out = await clean_text(_text(5), model="m", ollama_url=OLLAMA)
    paragraphs = out.split("\n\n")
    assert "Исходный абзац номер 1." in paragraphs and paragraphs.count("Очищенный абзац.") == 4
    assert llm_failure_reason() is None


@respx.mock
async def test_exactly_half_failing_is_still_not_a_failure():
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=_server_errors({0, 1}))
    assert await clean_text(_text(4), model="m", ollama_url=OLLAMA) is not None


@respx.mock
async def test_empty_answers_and_errors_together_count_towards_the_half():
    from services.text_cleaner import clean_text
    begin_llm_run(None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))

    def handler(request):
        user = json.loads(request.content)["messages"][-1]["content"]
        if "номер 0." in user or "номер 1." in user:
            return httpx.Response(500, json={"error": "boom"})
        if "номер 2." in user:
            return httpx.Response(200, json={"message": {"role": "assistant", "content": ""}, "done": True})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Очищенный абзац."}, "done": True})

    respx.post(CHAT).mock(side_effect=handler)
    assert await clean_text(_text(5), model="m", ollama_url=OLLAMA) is None       # 2 errors + 1 empty of 5 is more than half


@pytest.fixture
async def _empty_queue(client):
    from tests.baseline_helpers import reset_queue
    await reset_queue()
    yield
    await reset_queue()


@respx.mock
async def test_the_queue_cleanup_stage_with_a_missing_model_ends_failed_with_the_reason(client, seeded_video, _empty_queue):
    from services import queue_service as q
    await set_fmt(cleanup_status=None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=httpx.Response(404, json={"error": "model 'm' not found"}))
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await q._run_cleanup_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and row["cleanup_error"] == MISSING
    shown = (await client.get(f"/api/result/{VIDEO_ID}")).json()
    assert shown["cleanup_error"] == MISSING
    run = shown["stages"]["cleanup"]
    assert run["status"] == "failed" and run["error_code"]


@respx.mock
async def test_the_queue_cleanup_stage_with_server_errors_ends_failed_with_the_generic_reason(client, seeded_video, _empty_queue):
    from services import queue_service as q
    await set_fmt(cleanup_status=None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    await client.put("/api/settings/cleanup", json={"model": "m"})
    await q._run_cleanup_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["cleanup_status"] == "failed" and "No cleaned text was produced" in row["cleanup_error"]
