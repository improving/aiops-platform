"""Ollama registry importer: ``fetch(reference)`` reads the OCI
manifest of one ``name:tag`` (``GET
https://registry.ollama.ai/v2/library/{name}/manifests/{tag}``) and
parses it into a ``RegistryEntry``. There is no tag-listing endpoint
(``/v2/library/{name}/tags/list`` 404s), so unlike Hugging Face and
OpenRouter there is no real search: the "Add Ollama model" dialog's
query is a full reference and the answer is this one preview.
"""

import certifi
import httpx

from registry.entry import RegistryEntry, SourceError

BASE_URL = "https://registry.ollama.ai/v2/library"
TIMEOUT = 15.0
MODEL_LAYER_MEDIA_TYPE = "application/vnd.ollama.image.model"

# Small, well-known embedding models; every other tag is assumed chat.
EMBEDDING_MODEL_NAMES = frozenset(
    {
        "nomic-embed-text",
        "bge-m3",
        "all-minilm",
        "mxbai-embed-large",
        "snowflake-arctic-embed",
    }
)


def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        verify=certifi.where(), timeout=TIMEOUT, transport=transport
    )


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        detail = "The Ollama registry rate limited the request"
        if retry_after:
            detail += f"; retry after {retry_after}"
        raise SourceError(429, detail)
    raise SourceError(
        response.status_code,
        f"The Ollama registry answered {response.status_code}: "
        f"{response.text[:200]}",
    )


def _split_reference(reference: str) -> tuple[str, str]:
    name, sep, tag = reference.partition(":")
    return name, tag if sep else "latest"


def _model_layer_size(manifest: dict) -> int | None:
    for layer in manifest.get("layers") or []:
        if layer.get("mediaType") == MODEL_LAYER_MEDIA_TYPE:
            return layer.get("size")
    return None


def parse_manifest(name: str, tag: str, manifest: dict) -> RegistryEntry:
    """One registry manifest response into a ``RegistryEntry``. Pure:
    no network."""
    reference = f"{name}:{tag}"
    is_embedding = name in EMBEDDING_MODEL_NAMES
    capabilities = ["embedding"] if is_embedding else ["chat"]
    return RegistryEntry(
        source="ollama",
        source_id=reference,
        name=f"{name} {tag}",
        description=None,
        category="embedding" if is_embedding else "llm",
        subcategory=None,
        size=_model_layer_size(manifest),
        # The registry manifest carries no license metadata; the model
        # card page does, but that is not this API.
        license=None,
        parameters=None,
        context_length=None,
        capabilities=capabilities,
        formats=["gguf"],
        tags=[],
        raw=manifest,
        serving_options=[("Ollama", reference)],
    )


def fetch(
    reference: str, *, transport: httpx.BaseTransport | None = None
) -> RegistryEntry:
    """``reference`` is ``name`` or ``name:tag`` (``tag`` defaults to
    ``latest``, matching an unqualified ``ollama pull name``)."""
    name, tag = _split_reference(reference)
    url = f"{BASE_URL}/{name}/manifests/{tag}"
    with _client(transport) as client:
        try:
            response = client.get(url)
        except httpx.HTTPError as e:
            raise SourceError(
                502, f"The Ollama registry is not reachable: {e}"
            ) from e
    _raise_for_status(response)
    return parse_manifest(name, tag, response.json())
