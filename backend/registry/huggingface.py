"""Hugging Face Hub importer: ``search()`` previews and ``fetch()``
reads back one repo's metadata (``GET /api/models`` and
``GET /api/models/{repo}?blobs=true``), parsed into a ``RegistryEntry``
by the pure ``parse_model()`` (exercised on fixtures, no network).

The client is built with ``verify=certifi.where()``: ``make backend``
points ``SSL_CERT_FILE`` at the local CA only, which would make every
public host fail verification otherwise (certifi is an httpx
dependency, not the local CA).
"""

import certifi
import httpx

from registry.entry import RegistryEntry, SourceError

BASE_URL = "https://huggingface.co/api/models"
TIMEOUT = 15.0
# The fields the Hub search endpoint should expand for each result, so
# a search preview carries everything parse_model() needs.
SEARCH_EXPAND = (
    "cardData",
    "safetensors",
    "gated",
    "pipeline_tag",
    "library_name",
    "siblings",
)

_PIPELINE_CATEGORY = {
    "text-generation": "llm",
    "feature-extraction": "embedding",
    "sentence-similarity": "embedding",
}
_RERANK_PIPELINES = ("text-ranking", "text-classification")
_CAPABILITY_BY_CATEGORY = {
    "llm": ["chat"],
    "embedding": ["embedding"],
    "reranker": ["rerank"],
}


def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        verify=certifi.where(), timeout=TIMEOUT, transport=transport
    )


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        detail = "Hugging Face rate limited the request"
        if retry_after:
            detail += f"; retry after {retry_after}"
        raise SourceError(429, detail)
    raise SourceError(
        response.status_code,
        f"Hugging Face answered {response.status_code}: {response.text[:200]}",
    )


def _category(data: dict) -> str | None:
    pipeline_tag = data.get("pipeline_tag")
    if pipeline_tag in _PIPELINE_CATEGORY:
        return _PIPELINE_CATEGORY[pipeline_tag]
    if pipeline_tag in _RERANK_PIPELINES:
        tags = data.get("tags") or []
        if any("rerank" in tag.lower() for tag in tags):
            return "reranker"
    architectures = (data.get("config") or {}).get("architectures") or []
    if any(a.endswith("ForCausalLM") for a in architectures):
        return "llm"
    return None


def _license(data: dict) -> str | None:
    card_license = (data.get("cardData") or {}).get("license")
    if isinstance(card_license, str) and card_license:
        return card_license
    for tag in data.get("tags") or []:
        if tag.startswith("license:"):
            return tag.split(":", 1)[1]
    return None


def _parameters(data: dict) -> int | None:
    safetensors = data.get("safetensors") or {}
    if safetensors.get("total") is not None:
        return safetensors["total"]
    per_dtype = safetensors.get("parameters")
    if per_dtype:
        return sum(per_dtype.values())
    return None


def _is_gguf(data: dict) -> bool:
    if data.get("library_name") == "gguf":
        return True
    return any(
        s.get("rfilename", "").endswith(".gguf")
        for s in data.get("siblings") or []
    )


def _select_gguf_file(siblings: list[dict]) -> dict | None:
    """The Q4_K_M quant when the repo has one, else the first .gguf
    file; this same file is what the entry's size and its Ollama
    serving option's quant suffix come from."""
    gguf_files = [
        s for s in siblings if s.get("rfilename", "").endswith(".gguf")
    ]
    if not gguf_files:
        return None
    preferred = next(
        (s for s in gguf_files if "Q4_K_M" in s["rfilename"]), None
    )
    return preferred or gguf_files[0]


def _quant_suffix(filename: str) -> str:
    """``Qwen3-0.6B-Q8_0.gguf`` -> ``Q8_0``: the last ``-``-separated
    segment before the extension."""
    stem = filename[: -len(".gguf")]
    return stem.rsplit("-", 1)[-1]


def _size(data: dict, is_gguf: bool) -> int | None:
    siblings = data.get("siblings") or []
    if is_gguf:
        selected = _select_gguf_file(siblings)
        return selected.get("size") if selected else None
    total = sum(
        s.get("size", 0) or 0
        for s in siblings
        if s.get("rfilename", "").endswith(".safetensors")
    )
    return total or None


def _serving_options(
    data: dict, is_gguf: bool, category: str | None
) -> list[tuple[str, str]]:
    if data.get("gated"):
        return []
    repo_id = data["id"]
    if is_gguf:
        selected = _select_gguf_file(data.get("siblings") or [])
        if selected is None:
            return []
        quant = _quant_suffix(selected["rfilename"])
        return [("Ollama", f"hf.co/{repo_id}:{quant}")]
    if category == "llm":
        return [
            ("HuggingFace", repo_id),
            ("vLLM", repo_id),
            ("NIM", repo_id),
        ]
    if category in ("embedding", "reranker"):
        # TEI (text-embeddings-inference) only; no vLLM/NIM route.
        return [("HuggingFace", repo_id)]
    return []


def parse_model(data: dict) -> RegistryEntry:
    """One ``/api/models/{repo}`` response (or one ``/api/models``
    search result) into a ``RegistryEntry``. Pure: no network."""
    repo_id = data["id"]
    is_gguf = _is_gguf(data)
    category = _category(data)
    gated = bool(data.get("gated"))
    tags = list(data.get("tags") or [])
    if gated and "gated" not in tags:
        tags = [*tags, "gated"]
    return RegistryEntry(
        source="huggingface",
        source_id=repo_id,
        name=repo_id,
        description=None,
        category=category,
        subcategory=None,
        size=_size(data, is_gguf),
        license=_license(data),
        parameters=_parameters(data),
        context_length=None,
        capabilities=list(_CAPABILITY_BY_CATEGORY.get(category, [])),
        formats=["gguf"] if is_gguf else ["safetensors"],
        tags=tags,
        raw=data,
        serving_options=_serving_options(data, is_gguf, category),
    )


def search(
    query: str,
    limit: int = 20,
    *,
    transport: httpx.BaseTransport | None = None,
) -> list[RegistryEntry]:
    """Search previews for the "Import from Hugging Face" dialog."""
    params = [("search", query), ("limit", str(limit))]
    params += [("expand[]", field) for field in SEARCH_EXPAND]
    with _client(transport) as client:
        try:
            response = client.get(BASE_URL, params=params)
        except httpx.HTTPError as e:
            raise SourceError(
                502, f"Hugging Face is not reachable: {e}"
            ) from e
    _raise_for_status(response)
    return [parse_model(m) for m in response.json()]


def fetch(
    source_id: str, *, transport: httpx.BaseTransport | None = None
) -> RegistryEntry:
    """One repo's metadata, by its id (``owner/repo``)."""
    url = f"{BASE_URL}/{source_id}"
    with _client(transport) as client:
        try:
            response = client.get(url, params={"blobs": "true"})
        except httpx.HTTPError as e:
            raise SourceError(
                502, f"Hugging Face is not reachable: {e}"
            ) from e
    _raise_for_status(response)
    return parse_model(response.json())
