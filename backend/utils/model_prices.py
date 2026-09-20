"""LiteLLM's public prices and context-window catalog.

``load_prices()`` fetches
``model_prices_and_context_window.json`` from the LiteLLM repository and
caches it in-process; under ``TEST_MODE`` it reads the small
``raw_data/model_prices.sample.json`` fixture instead, so tests never hit
the network. ``lookup_price()`` maps a provider kind and a bare model id
to the entry, trying the provider-prefixed and OpenRouter-prefixed keys
the catalog uses for non-OpenAI providers.
"""

import os
import time
from dataclasses import dataclass

import httpx

from logger import setup_logger
from paths import RAW_DATA_DIR
from utils.tls import public_ca_bundle

logger = setup_logger(__name__)

PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
SAMPLE_FILE = RAW_DATA_DIR / "model_prices.sample.json"
FETCH_TIMEOUT = 10.0

# After a failed fetch, do not try again for this many seconds.
RETRY_AFTER = 300.0

_cache: dict[str, dict] = {}
_failed_at: float | None = None


@dataclass(frozen=True)
class ModelPrice:
    max_input_tokens: int | None
    max_output_tokens: int | None
    input_cost_per_token: float | None
    output_cost_per_token: float | None
    mode: str | None
    provider: str | None
    # ``supports_function_calling``; None when the catalog does not say.
    tools: bool | None = None


def _is_test_mode() -> bool:
    return os.environ.get("TEST_MODE", "false").lower() == "true"


def load_prices() -> dict[str, dict]:
    """The catalog, cached in-process. TEST_MODE reads the sample file;
    otherwise a failed fetch logs and returns an empty dict."""
    if _cache:
        return _cache
    if _is_test_mode():
        import json

        with open(SAMPLE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        _cache.update(data)
        return _cache
    global _failed_at
    if _failed_at is not None and time.monotonic() - _failed_at < RETRY_AFTER:
        return {}
    try:
        response = httpx.get(
            PRICES_URL, timeout=FETCH_TIMEOUT, verify=public_ca_bundle()
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.error("Could not fetch the LiteLLM prices catalog: %s", e)
        _failed_at = time.monotonic()
        return {}
    _cache.update(data)
    return _cache


def _to_price(entry: dict) -> ModelPrice:
    return ModelPrice(
        max_input_tokens=entry.get("max_input_tokens"),
        max_output_tokens=entry.get("max_output_tokens"),
        input_cost_per_token=entry.get("input_cost_per_token"),
        output_cost_per_token=entry.get("output_cost_per_token"),
        mode=entry.get("mode"),
        provider=entry.get("litellm_provider"),
        tools=entry.get("supports_function_calling"),
    )


def lookup_price(kind: str, model: str) -> ModelPrice | None:
    """Try the bare model id, then ``<kind>/<model>``, then
    ``openrouter/<model>`` (OpenRouter ids already carry the upstream
    provider, for example ``openai/gpt-4o-mini``)."""
    prices = load_prices()
    for key in (model, f"{kind}/{model}", f"openrouter/{model}"):
        entry = prices.get(key)
        if entry is not None:
            return _to_price(entry)
    return None
