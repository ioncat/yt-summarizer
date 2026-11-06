"""num_ctx sizing for every Ollama chat call (NS-26). The Ollama HTTP calls are mocked with respx."""
import json

import httpx
import pytest
import respx

from services.ollama_options import (
    DEFAULT_MAX_NUM_CTX, MAX_NUM_CTX, MIN_NUM_CTX, apply_max_num_ctx, build_options, compute_num_ctx, llm_scope,
    parse_max_num_ctx,
)

OLLAMA = "http://localhost:11434"
TAGS = f"{OLLAMA}/api/tags"
CHAT = f"{OLLAMA}/api/chat"
LONG_TEXT = "Это длинный абзац для проверки. " * 400  # ~12,800 chars ~ 4,300 tokens


@pytest.fixture(autouse=True)
def _reset_cap():
    apply_max_num_ctx(None)
    yield
    apply_max_num_ctx(None)


# --- the rule ---------------------------------------------------------------

def test_rule_buckets_grow_with_the_prompt():
    assert compute_num_ctx("x" * 30) == 8192            # tiny prompt still leaves room for thinking + answer
    assert compute_num_ctx("x" * 11_553) == 16384       # the 3,851-token prompt that failed at 4096
    assert compute_num_ctx("x" * 40_000) == 32768
    assert compute_num_ctx("x" * 120_000) == 32768      # above the cap -> the cap


def test_cap_is_respected_and_bad_values_fall_back():
    assert compute_num_ctx("x" * 40_000, max_ctx=16384) == 16384
    assert compute_num_ctx("x" * 80_000, max_ctx=65536) == 65536
    assert parse_max_num_ctx("8192") == 8192
    for not_a_number in (None, "", "abc"):
        assert parse_max_num_ctx(not_a_number) == DEFAULT_MAX_NUM_CTX
    with llm_scope("8192"):
        assert compute_num_ctx("x" * 40_000) == 8192
    assert compute_num_ctx("x" * 40_000) == 32768       # scope restored


def test_cap_is_clamped_to_4096_at_the_bottom_and_65536_at_the_top():
    assert MIN_NUM_CTX == 4096 and MAX_NUM_CTX == 65536
    for low in ("100", 0, "-5", "4095"):
        assert parse_max_num_ctx(low) == 4096
    for high in ("131072", 1_000_000, "65537"):
        assert parse_max_num_ctx(high) == 65536
    assert parse_max_num_ctx("65536") == 65536 and parse_max_num_ctx("4096") == 4096
    # an explicit max_ctx is clamped the same way, so compute_num_ctx never returns a huge cap
    assert compute_num_ctx("x" * 900_000, max_ctx=1_000_000) == 65536
    assert compute_num_ctx("x" * 900_000, max_ctx=100) == 4096
    with llm_scope("999999"):
        assert compute_num_ctx("x" * 900_000) == 65536
    with llm_scope("10"):
        assert compute_num_ctx("x" * 900_000) == 4096


def test_small_reserve_keeps_cleanup_paragraphs_at_4k():
    assert compute_num_ctx("s" * 200, "p" * 500, reserve_tokens=2048) == 4096
    assert compute_num_ctx("p" * 9_000, reserve_tokens=2048) == 8192


def test_build_options_keeps_other_options():
    opts = build_options("x" * 30, temperature=0.2)
    assert opts == {"temperature": 0.2, "num_ctx": 8192}


# --- every call site sends num_ctx -----------------------------------------

def _capture(route, content="Answer text."):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "done": True})

    route.mock(side_effect=handler)
    return seen


@respx.mock
async def test_summary_single_pass_long_input_gets_larger_num_ctx():
    from services.text_summarizer import summarize_text
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    seen = _capture(respx.post(CHAT))
    await summarize_text(LONG_TEXT, model="m", ollama_url=OLLAMA)
    assert seen[0]["options"]["num_ctx"] == 16384
    seen.clear()
    await summarize_text("Короткий текст для сводки.", model="m", ollama_url=OLLAMA)
    assert seen[0]["options"]["num_ctx"] == 8192


@respx.mock
async def test_summary_map_reduce_and_full_extract_send_num_ctx():
    from services.text_summarizer import extract_notes, summarize_text
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    seen = _capture(respx.post(CHAT))
    await summarize_text("word " * 6000, model="m", ollama_url=OLLAMA, force_map_reduce=True)  # chunks + reduce
    assert len(seen) >= 2 and all("num_ctx" in c["options"] for c in seen)
    seen.clear()
    await extract_notes("## A\n\n" + LONG_TEXT + "\n\n## B\n\nshort", model="m", ollama_url=OLLAMA)
    assert len(seen) == 2
    assert seen[0]["options"]["num_ctx"] == 16384 and seen[1]["options"]["num_ctx"] == 8192


@respx.mock
async def test_cleanup_paragraph_keeps_4k_and_a_huge_paragraph_grows():
    from services.text_cleaner import clean_text
    seen = _capture(respx.post(CHAT))
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    await clean_text("Обычный абзац из диктора. " * 18, model="m", ollama_url=OLLAMA)
    assert seen[0]["options"]["num_ctx"] == 4096
    seen.clear()
    await clean_text("Огромный абзац без разрыва. " * 600, model="m", ollama_url=OLLAMA)
    assert seen[0]["options"]["num_ctx"] > 4096


@respx.mock
async def test_mindmap_stream_request_sends_num_ctx():
    from services.text_mindmapper import generate_mindmap
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        body = json.dumps({"message": {"content": "# Root"}, "done": True}) + "\n"
        return httpx.Response(200, content=body.encode())

    respx.post(CHAT).mock(side_effect=handler)
    assert await generate_mindmap(LONG_TEXT, OLLAMA, "m", "Russian") == "# Root"
    assert seen[0]["options"]["num_ctx"] == 16384


@respx.mock
async def test_chat_proxy_floor_is_chat_num_ctx_and_cap_is_the_larger_of_it_and_llm_max_num_ctx(client):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b'{"message":{"content":"hi"},"done":true}\n')

    respx.post(CHAT).mock(side_effect=handler)
    short = [{"role": "user", "content": "Привет"}]
    long_ = [{"role": "user", "content": LONG_TEXT}]          # computed size 16384
    huge = [{"role": "user", "content": "x" * 120_000}]       # computed size 65536 if allowed

    async def chat(messages, chat_ctx, llm_ctx):
        await client.put("/api/settings/app", json={"chat_num_ctx": chat_ctx, "llm_max_num_ctx": llm_ctx})
        r = await client.post("/api/chat", json={"model": "m", "messages": messages})
        assert r.status_code == 200
        return seen[-1]["options"]["num_ctx"]

    async def too_long(messages, chat_ctx, llm_ctx):
        """The input does not fit the cap: nothing is sent to Ollama, the chat gets one error line saying how to fix it."""
        await client.put("/api/settings/app", json={"chat_num_ctx": chat_ctx, "llm_max_num_ctx": llm_ctx})
        sent_before = len(seen)
        r = await client.post("/api/chat", json={"model": "m", "messages": messages})
        assert r.status_code == 200 and len(seen) == sent_before
        error = json.loads(r.content)["error"]
        return "too long for the context limit" in error and "Settings → General" in error

    try:
        assert await chat(short, "32768", "32768") == 32768    # short chat: the old fixed value
        assert await chat(long_, "32768", "32768") == 32768    # bucket changes inside the floor: no reload
        assert await too_long(huge, "32768", "32768")          # cap = max(32768, 32768): the input does not fit -> an error line (NS-26)
        assert await chat(huge, "32768", "65536") == 65536     # llm_max_num_ctx raises the cap above the floor
        assert await chat(long_, "8192", "32768") == 16384     # computed value above a small floor
        assert await too_long(huge, "8192", "32768")           # llm_max_num_ctx is the cap: too long for it
        assert await chat(long_, "4096", "8192") == 8192       # ... also when it is small: it still fits 8K with room for a short answer
        assert await chat(short, "8192", "4096") == 8192       # floor never lowered by a small llm cap
        assert await too_long(huge, "8192", "4096")            # cap = max(chat, llm) = 8192: too long
    finally:
        await client.put("/api/settings/app", json={"chat_num_ctx": "32768", "llm_max_num_ctx": "32768"})


@respx.mock
async def test_chat_proxy_validates_chat_num_ctx(client):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b'{"message":{"content":"hi"},"done":true}\n')

    respx.post(CHAT).mock(side_effect=handler)
    short = [{"role": "user", "content": "Привет"}]
    try:
        for value, expected in (("abc", 32768), ("", 32768), ("999999", 65536), ("100", 8192)):  # tiny floor: the computed size for a short chat (8192) wins
            await client.put("/api/settings/app", json={"chat_num_ctx": value, "llm_max_num_ctx": "32768"})
            r = await client.post("/api/chat", json={"model": "m", "messages": short})
            assert r.status_code == 200, value                 # never a 500
            assert seen[-1]["options"]["num_ctx"] == expected, value
    finally:
        await client.put("/api/settings/app", json={"chat_num_ctx": "32768"})


async def test_cap_setting_is_stored_and_read_through_the_settings_api(client):
    r = await client.get("/api/settings")
    assert r.json()["app"]["llm_max_num_ctx"] in ("32768", None)
    await client.put("/api/settings/app", json={"llm_max_num_ctx": "16384"})
    assert (await client.get("/api/settings")).json()["app"]["llm_max_num_ctx"] == "16384"
    await client.put("/api/settings/app", json={"llm_max_num_ctx": "32768"})


async def test_stage_runner_applies_the_cap_setting(client, seeded_video):
    """A summary run reads llm_max_num_ctx and passes it to the LLM call as the cap."""
    from unittest.mock import patch
    from services.ollama_options import compute_num_ctx as cn

    seen_cap = {}

    async def fake_summarize(text, **kw):
        seen_cap["ctx"] = cn("x" * 40_000)  # what a call made inside the runner would get
        return "S", "single", 1

    await client.put("/api/settings/summarization", json={"model": "m"})
    await client.put("/api/settings/app", json={"ollama_url": OLLAMA, "llm_max_num_ctx": "8192"})
    from tests.baseline_helpers import run_queued_stage
    with patch("services.text_summarizer.summarize_text", fake_summarize):
        await client.post(f"/api/result/{seeded_video['video_id']}/summary")
        await run_queued_stage(seeded_video["video_id"], "summary")  # the queue worker runs it (NS-11 stage 3)
    await client.put("/api/settings/app", json={"llm_max_num_ctx": "32768"})
    assert seen_cap["ctx"] == 8192
