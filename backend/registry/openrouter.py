"""OpenRouter importer: ``list_models()`` reads ``GET
/api/v1/models`` (no key needed) and parses every entry into a
``RegistryEntry``, all category "llm" (OpenRouter is a hosted
chat/completions aggregator; every model is a chat target, ``vision``
is added to ``capabilities`` when the model also accepts image
input)."""

import certifi
import httpx

from registry.entry import RegistryEntry, SourceError

BASE_URL = "https://openrouter.ai/api/v1/models"
TIMEOUT = 15.0


def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        verify=certifi.where(), timeout=TIMEOUT, transport=transport
    )


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        detail = "OpenRouter rate limited the request"
        if retry_after:
            detail += f"; retry after {retry_after}"
        raise SourceError(429, detail)
    raise SourceError(
        response.status_code,
        f"OpenRouter answered {response.status_code}: {response.text[:200]}",
    )


def parse_model(data: dict) -> RegistryEntry:
    """One ``/api/v1/models`` entry into a ``RegistryEntry``. Pure: no
    network."""
    model_id = data["id"]
    architecture = data.get("architecture") or {}
    input_modalities = architecture.get("input_modalities") or []
    capabilities = ["chat"]
    if "image" in input_modalities:
        capabilities.append("vision")
    return RegistryEntry(
        source="openrouter",
        source_id=model_id,
        name=data.get("name") or model_id,
        description=data.get("description"),
        category="llm",
        subcategory=None,
        size=None,
        license=None,
        parameters=None,
        context_length=data.get("context_length"),
        capabilities=capabilities,
        formats=["hosted"],
        tags=[],
        raw={"pricing": data.get("pricing")},
        serving_options=[("openrouter", model_id)],
    )


def list_models(
    *, transport: httpx.BaseTransport | None = None
) -> list[RegistryEntry]:
    with _client(transport) as client:
        try:
            response = client.get(BASE_URL)
        except httpx.HTTPError as e:
            raise SourceError(502, f"OpenRouter is not reachable: {e}") from e
    _raise_for_status(response)
    return [parse_model(m) for m in response.json()["data"]]
