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


def test_lookup_carries_function_calling():
    assert mp.lookup_price("openai", "gpt-4o-mini").tools is True
    # The catalog says nothing for an embedding model: unknown, not False.
    assert mp.lookup_price("openai", "text-embedding-3-small").tools is None


def test_load_prices_is_cached(monkeypatch):
    mp._cache.clear()
    first = mp.load_prices()
    assert "gpt-4o-mini" in first
    assert mp.load_prices() is first


def test_a_failed_fetch_is_not_repeated_at_once(monkeypatch):
    # /chat/targets asks the catalog on every poll; an unreachable
    # catalog must not cost one 10 s fetch per poll.
    import httpx

    calls = []

    def failing_get(*args, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("no network")

    mp._cache.clear()
    monkeypatch.setattr(mp, "_is_test_mode", lambda: False)
    monkeypatch.setattr(mp, "_failed_at", None)
    monkeypatch.setattr(mp.httpx, "get", failing_get)
    assert mp.load_prices() == {}
    assert mp.load_prices() == {}
    assert len(calls) == 1
