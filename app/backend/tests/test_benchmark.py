"""NS-26: the benchmark takes the same LLM context limit as the queue's stages."""


async def test_a_benchmark_run_uses_the_context_limit_of_the_settings(client):
    """NS-26: the benchmark ignored llm_max_num_ctx (it ran with the built-in default)."""
    from unittest.mock import patch
    from services import benchmark_service, ollama_options
    seen = {}

    async def fake_clean(text, **kwargs):
        seen["limit"] = ollama_options._max_num_ctx.get()
        return "cleaned"

    await client.put("/api/settings/app", json={"llm_max_num_ctx": "8192"})
    with patch("services.text_cleaner.clean_text", fake_clean):
        await benchmark_service._run_one_model(1, "cleanup", "m", "some text", "single", False, "http://localhost:11434", None, "vid")
    assert seen["limit"] == 8192
    await client.put("/api/settings/app", json={"llm_max_num_ctx": "65536"})
    with patch("services.text_cleaner.clean_text", fake_clean):
        await benchmark_service._run_one_model(1, "cleanup", "m", "some text", "single", False, "http://localhost:11434", None, "vid")
    assert seen["limit"] == 65536
