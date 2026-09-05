"""Hosted-provider discovery: the platform's provider kinds, the naming
of the provider's credential Secret, and the calls to each provider's
model-listing endpoint.

``enrich()`` is a purely local lookup against ``utils/model_prices.py``:
once a model id is known (picked from a ``discover_models()`` preflight,
or already stored on a ``provider_models`` row), the capability,
context length and prices used elsewhere never need the network again.
"""

import uuid
from dataclasses import dataclass

import httpx

from logger import setup_logger
from utils import model_prices
from utils.gateway import id8
from utils.tls import public_ca_bundle

logger = setup_logger(__name__)

PROVIDER_KINDS = ("openai", "anthropic", "gemini", "groq", "openrouter")
SECRET_KEY = "api-key"
DISCOVERY_TIMEOUT = 15.0

# The capabilities this platform exposes as chat targets; a catalog
# entry with any other known mode (tts, image, moderation, audio, ...)
# is dropped from discovery.
_CHAT_LIKE_MODES = {"chat", "embedding"}


def provider_secret_name(provider_id: uuid.UUID) -> str:
    return f"prov-{id8(provider_id)}-credentials"


@dataclass(frozen=True)
class DiscoveredModel:
    id: str
    display_name: str
    context_length: int | None
    capability: str


class ProviderError(Exception):
    """The provider rejected the key (``status=400``) or could not be
    reached (``status=502``)."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def enrich(kind: str, model_id: str) -> model_prices.ModelPrice | None:
    return model_prices.lookup_price(kind, model_id)


def capability_for(kind: str, model_id: str) -> str | None:
    """The capability to expose a model under, or None to drop it (a
    known non-chat, non-embedding mode). Unknown models default to
    "chat"."""
    price = enrich(kind, model_id)
    if price is None or price.mode is None:
        return "chat"
    return price.mode if price.mode in _CHAT_LIKE_MODES else None


def _request(kind: str, url: str, **kwargs) -> httpx.Response:
    try:
        response = httpx.get(
            url,
            timeout=DISCOVERY_TIMEOUT,
            verify=public_ca_bundle(),
            **kwargs,
        )
    except httpx.HTTPError as e:
        raise ProviderError(502, f"{kind} is not reachable: {e}") from e
    if response.status_code in (401, 403):
        raise ProviderError(
            400, f"The provider rejected the key: {response.text[:200]}"
        )
    if response.status_code >= 400:
        raise ProviderError(
            502,
            f"{kind} answered {response.status_code}: {response.text[:200]}",
        )
    return response


def _list_openai(api_key: str, base_url: str | None):
    url = f"{(base_url or 'https://api.openai.com/v1').rstrip('/')}/models"
    response = _request(
        "openai", url, headers={"authorization": f"Bearer {api_key}"}
    )
    return [(m["id"], m["id"], None) for m in response.json()["data"]]


def _list_anthropic(api_key: str, base_url: str | None):
    url = f"{(base_url or 'https://api.anthropic.com/v1').rstrip('/')}/models"
    response = _request(
        "anthropic",
        url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    return [
        (m["id"], m.get("display_name") or m["id"], m.get("max_input_tokens"))
        for m in response.json()["data"]
    ]


def _list_gemini(api_key: str, base_url: str | None):
    url = (
        f"{(base_url or 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')}"
        "/models"
    )
    response = _request("gemini", url, params={"key": api_key})
    models = []
    for m in response.json().get("models", []):
        model_id = m["name"].split("/", 1)[-1]
        models.append(
            (
                model_id,
                m.get("displayName") or model_id,
                m.get("inputTokenLimit"),
            )
        )
    return models


def _list_groq(api_key: str, base_url: str | None):
    url = (
        f"{(base_url or 'https://api.groq.com/openai/v1').rstrip('/')}/models"
    )
    response = _request(
        "groq", url, headers={"authorization": f"Bearer {api_key}"}
    )
    return [
        (m["id"], m["id"], m.get("context_window"))
        for m in response.json()["data"]
    ]


def _list_openrouter(api_key: str, base_url: str | None):
    url = f"{(base_url or 'https://openrouter.ai/api/v1').rstrip('/')}/models"
    headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    response = _request("openrouter", url, headers=headers)
    return [
        (m["id"], m.get("name") or m["id"], m.get("context_length"))
        for m in response.json()["data"]
    ]


_LISTERS = {
    "openai": _list_openai,
    "anthropic": _list_anthropic,
    "gemini": _list_gemini,
    "groq": _list_groq,
    "openrouter": _list_openrouter,
}


def discover_models(
    kind: str, api_key: str, base_url: str | None = None
) -> list[DiscoveredModel]:
    """The provider's models, enriched with the local capability rule.
    Entries whose known mode is not chat or embedding are dropped."""
    lister = _LISTERS.get(kind)
    if lister is None:
        raise ProviderError(400, f"Unknown provider kind: {kind}")
    discovered = []
    for model_id, display_name, provider_context in lister(api_key, base_url):
        capability = capability_for(kind, model_id)
        if capability is None:
            continue
        price = enrich(kind, model_id)
        context_length = provider_context
        if context_length is None and price is not None:
            context_length = price.max_input_tokens
        discovered.append(
            DiscoveredModel(
                id=model_id,
                display_name=display_name,
                context_length=context_length,
                capability=capability,
            )
        )
    return discovered
