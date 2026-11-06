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


# --- the room for the answer scales with the limit (review: Medium) -------------------------------------------------------------

def words(chars: int) -> str:
    """A transcript-like text of about `chars` characters: paragraphs of ~600 characters, as the formatter writes them."""
    paragraph = "слово " * 100
    count = chars // len(paragraph) + 1
    return ("\n\n").join([paragraph.strip()] * count)[:chars]


@pytest.mark.parametrize("cap,fits_chars,too_long_chars", [
    ("4096", 6_000, 12_000),         # 4K: ~3000 tokens of input + 1024 for the answer
    ("8192", 20_000, 25_000),        # 8K: a 20,000-character transcript fits (it used to be refused above ~12,000)
    ("16384", 40_000, 50_000),
])
def test_what_a_limit_takes_in(cap, fits_chars, too_long_chars):
    begin_llm_run(cap)
    assert build_options(words(fits_chars))["num_ctx"] <= int(cap)
    with pytest.raises(ContextTooSmall):
        build_options(words(too_long_chars))
    assert llm_failure_reason() is not None


def test_the_message_says_the_answer_needs_room():
    begin_llm_run("4096")
    with pytest.raises(ContextTooSmall) as caught:
        build_options(words(30_000))
    assert "room for the answer" in str(caught.value) and "cut off" in str(caught.value)
    assert classify_error(str(caught.value)) == "context_too_small"


def test_a_small_reserve_is_not_raised_to_the_default():
    """A call that only asks for a small reserve (cleanup paragraphs) is refused only when even that does not fit."""
    begin_llm_run("4096")
    assert build_options(words(8_000), reserve_tokens=512)["num_ctx"] == 4096
    with pytest.raises(ContextTooSmall):
        build_options(words(12_000), reserve_tokens=512)


@pytest.mark.parametrize("cap,limit", [("4096", 6144), ("8192", 18432), ("16384", 24000), ("32768", 24000), ("65536", 24000)])
def test_the_single_pass_threshold_follows_the_limit(cap, limit):
    from services.text_summarizer import single_pass_limit_chars
    begin_llm_run(cap)
    assert single_pass_limit_chars() == limit


def ollama_answers(seen: list[int]):
    def handler(request):
        import json
        seen.append(json.loads(request.content)["options"]["num_ctx"])
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Answer."}, "done": True})
    return handler


@respx.mock
async def test_a_20000_character_transcript_is_summarized_at_8k_in_pieces():
    from services.text_summarizer import summarize_text
    begin_llm_run("8192")
    seen: list[int] = []
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=ollama_answers(seen))
    result, mode, chunks = await summarize_text(words(20_000), model="m", ollama_url=OLLAMA)
    assert result and mode == "map_reduce" and chunks > 1                   # not a failure: map-reduce
    assert seen and max(seen) <= 8192 and llm_failure_reason() is None


@respx.mock
async def test_a_15000_character_transcript_is_still_one_call_at_8k_and_a_6000_one_at_4k():
    from services.text_summarizer import summarize_text
    for cap, chars in (("8192", 15_000), ("4096", 5_000)):
        begin_llm_run(cap)
        seen: list[int] = []
        respx.reset()
        respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
        respx.post(CHAT).mock(side_effect=ollama_answers(seen))
        result, mode, chunks = await summarize_text(words(chars), model="m", ollama_url=OLLAMA)
        assert result and mode == "single" and chunks == 1 and len(seen) == 1 and seen[0] <= int(cap), cap


@respx.mock
async def test_at_4k_a_longer_text_goes_in_pieces_instead_of_failing():
    from services.text_summarizer import summarize_text
    begin_llm_run("4096")
    seen: list[int] = []
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=ollama_answers(seen))
    result, mode, chunks = await summarize_text(words(9_000), model="m", ollama_url=OLLAMA)
    assert result and mode == "map_reduce" and chunks > 1 and max(seen) <= 4096


@respx.mock
async def test_a_20000_character_transcript_gets_a_mind_map_at_8k():
    from services.text_mindmapper import generate_mindmap
    begin_llm_run("8192")
    seen: list[int] = []

    def handler(request):
        import json
        seen.append(json.loads(request.content)["options"]["num_ctx"])
        return httpx.Response(200, content=b'{"message":{"content":"# Root"},"done":true}\n')

    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=handler)
    assert await generate_mindmap(words(20_000), OLLAMA, "m", "Russian") == "# Root"
    assert seen == [8192] and llm_failure_reason() is None


@respx.mock
async def test_the_summary_stage_in_the_queue_works_at_8k_for_a_20000_character_transcript(client, seeded_video):
    from services import queue_service as q
    await client.put("/api/settings/summarization", json={"model": "m"})
    await client.put("/api/settings/app", json={"ollama_url": OLLAMA, "llm_max_num_ctx": "8192"})
    await set_fmt(formatted_text=words(20_000), cleaned_text=None)
    seen: list[int] = []
    respx.get(TAGS).mock(return_value=httpx.Response(200, json={"models": []}))
    respx.post(CHAT).mock(side_effect=ollama_answers(seen))
    await q._run_summary_stage(VIDEO_ID, 1)
    row = await fmt_row()
    assert row["summary_status"] == "done" and row["summary_mode"] == "map_reduce"
    assert max(seen) <= 8192
