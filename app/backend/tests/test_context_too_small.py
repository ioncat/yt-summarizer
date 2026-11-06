"""NS-26: an input that does not fit the context limit (with room for the answer) used to be cut off by Ollama without a word. Now the
call is not made: the step fails with its reason and the code context_too_small."""
import httpx
import pytest
import respx

from services import ollama_options
from services.ollama_options import ContextTooSmall, begin_llm_run, build_options, llm_failure_reason
from services.stage_codes import classify_error
from tests.baseline_helpers import VIDEO_ID, fmt_row, set_fmt

OLLAMA = "http://localhost:11434"
TAGS = f"{OLLAMA}/api/tags"
CHAT = f"{OLLAMA}/api/chat"
BIG = "слово " * 6000                      # ~12,000 tokens: over a 4096 limit, inside the default 32768


def test_an_input_above_the_limit_raises_and_records_its_reason():
    begin_llm_run("4096")
    with pytest.raises(ContextTooSmall) as caught:
        build_options(BIG, temperature=0.1)
    reason = llm_failure_reason()
    assert reason == str(caught.value) and "too long for the context limit (4096)" in reason
    assert "Settings → General" in reason
    assert classify_error(reason) == "context_too_small"


def test_an_input_that_fits_is_unchanged():
    begin_llm_run("32768")
    options = build_options("short text", temperature=0.1)
    assert options["temperature"] == 0.1 and options["num_ctx"] in (4096, 8192)
    assert llm_failure_reason() is None


def test_the_limit_is_the_cap_not_the_biggest_bucket():
    begin_llm_run("65536")
    assert build_options(BIG)["num_ctx"] >= 16384           # fits a bigger limit


@respx.mock
async def test_the_summary_makes_no_call_and_leaves_its_reason():
    from services.text_summarizer import summarize_text
    begin_llm_run("4096")
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    route = respx.post(CHAT).mock(return_value=httpx.Response(200, json={"message": {"content": "x"}, "done": True}))
    result, mode, _ = await summarize_text(BIG, model="m", ollama_url=OLLAMA)
    assert result is None and not route.called
    assert classify_error(llm_failure_reason()) == "context_too_small"


@respx.mock
async def test_the_mind_map_makes_no_call_and_leaves_its_reason():
    from services.text_mindmapper import generate_mindmap
    begin_llm_run("4096")
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    route = respx.post(CHAT).mock(return_value=httpx.Response(200, content=b'{"message":{"content":"# x"},"done":true}\n'))
    assert await generate_mindmap(BIG, OLLAMA, "m", "Russian") is None
    assert not route.called and classify_error(llm_failure_reason()) == "context_too_small"


@respx.mock
async def test_a_summary_stage_in_the_queue_fails_with_the_code(client, seeded_video):
    from services import queue_service as q
    await client.put("/api/settings/summarization", json={"model": "m"})
    await client.put("/api/settings/app", json={"ollama_url": OLLAMA, "llm_max_num_ctx": "4096"})
    await set_fmt(formatted_text=BIG, cleaned_text=None)
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    route = respx.post(CHAT).mock(return_value=httpx.Response(200, json={"message": {"content": "x"}, "done": True}))
    await q._run_summary_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["summary_status"] == "failed" and "too long for the context limit" in row["summary_error"]
    assert not route.called
    stage = (await client.get(f"/api/result/{VIDEO_ID}")).json()["stages"]["summary"]
    assert stage["status"] == "failed" and stage["error_code"] == "context_too_small"


async def test_the_default_limit_still_lets_a_long_video_through(client):
    """The limit is the owner's setting (default 32K): a normal long text is not refused."""
    assert ollama_options.DEFAULT_MAX_NUM_CTX == 32768
    begin_llm_run(None)
    assert build_options(BIG)["num_ctx"] >= 16384


@respx.mock
async def test_cleanup_of_one_huge_paragraph_fails_with_the_reason_and_sends_nothing():
    from services.text_cleaner import clean_text
    begin_llm_run("4096")
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    route = respx.post(CHAT).mock(return_value=httpx.Response(200, json={"message": {"content": "x"}, "done": True}))
    assert await clean_text(BIG, model="m", ollama_url=OLLAMA) is None            # the only paragraph is over the limit
    assert not route.called and classify_error(llm_failure_reason()) == "context_too_small"
