from utils import model_prices as mp


def test_lookup_uses_kind_prefixes():
    # TEST_MODE: the sample file ships gpt-4o-mini, gemini/gemini-2.5-flash,
    # groq/llama-3.3-70b-versatile, anthropic claude-3-5-haiku-20241022,
    # openrouter/openai/gpt-4o-mini, text-embedding-3-small.
    assert mp.lookup_price("openai", "gpt-4o-mini").mode == "chat"
    assert (
        mp.lookup_price("gemini", "gemini-2.5-flash").max_input_tokens
        == 1048576
    )
    assert mp.lookup_price("groq", "llama-3.3-70b-versatile").provider == (
        "groq"
    )
    assert (
        mp.lookup_price(
            "anthropic", "claude-3-5-haiku-20241022"
        ).input_cost_per_token
        > 0
    )
    assert mp.lookup_price("openrouter", "openai/gpt-4o-mini").mode == "chat"
    assert mp.lookup_price("openai", "text-embedding-3-small").mode == (
        "embedding"
    )
    assert mp.lookup_price("openai", "no-such-model") is None


def test_load_prices_is_cached(monkeypatch):
    mp._cache.clear()
    first = mp.load_prices()
    assert "gpt-4o-mini" in first
    assert mp.load_prices() is first
