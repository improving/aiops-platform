"""Importer tests: every parser runs on a fixture recorded from the
real API (backend/test_fixtures/), never the network. search()/fetch()
are exercised against an httpx.MockTransport so the URL and parameters
sent are checked without a real request either.
"""

import json

import httpx
import pytest

from paths import BACKEND_DIR
from registry import huggingface as hf
from registry import ollama, sources
from registry import openrouter as orr
from registry.entry import SourceError

FIXTURES = BACKEND_DIR / "test_fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


# --- Hugging Face -----------------------------------------------------


def test_parse_model_safetensors_llm():
    entry = hf.parse_model(_load("hf_model_qwen3_0_6b.json"))
    assert entry.source == "huggingface"
    assert entry.source_id == "Qwen/Qwen3-0.6B"
    assert entry.name == "Qwen/Qwen3-0.6B"
    assert entry.category == "llm"
    assert entry.license == "apache-2.0"
    assert entry.parameters == 751632384
    assert entry.capabilities == ["chat"]
    assert entry.formats == ["safetensors"]
    assert "gated" not in entry.tags
    # model.safetensors is the only .safetensors sibling in the fixture.
    assert entry.size == 1503300328
    assert entry.serving_options == [
        ("HuggingFace", "Qwen/Qwen3-0.6B"),
        ("vLLM", "Qwen/Qwen3-0.6B"),
        ("NIM", "Qwen/Qwen3-0.6B"),
    ]
    assert entry.raw["id"] == "Qwen/Qwen3-0.6B"


def test_parse_model_gguf_repo_picks_the_only_quant_file():
    """The real Qwen/Qwen3-0.6B-GGUF repo has a single quant
    (Q8_0, no Q4_K_M): the importer must fall back to it, not fail."""
    entry = hf.parse_model(_load("hf_model_qwen3_0_6b_gguf.json"))
    assert entry.category == "llm"
    assert entry.formats == ["gguf"]
    assert entry.size == 639446688  # the .gguf file's own size
    assert entry.serving_options == [
        ("Ollama", "hf.co/Qwen/Qwen3-0.6B-GGUF:Q8_0")
    ]


def test_parse_model_gguf_repo_prefers_q4_k_m_when_present():
    """A repo with several quants picks Q4_K_M over any other, even
    when it is not the first .gguf sibling listed."""
    data = {
        "id": "org/multi-quant-gguf",
        "gated": False,
        "pipeline_tag": "text-generation",
        "tags": ["gguf"],
        "library_name": "gguf",
        "config": {},
        "cardData": {},
        "siblings": [
            {"rfilename": "model-Q8_0.gguf", "size": 900},
            {"rfilename": "model-Q4_K_M.gguf", "size": 500},
            {"rfilename": "model-Q2_K.gguf", "size": 300},
        ],
    }
    entry = hf.parse_model(data)
    assert entry.size == 500
    assert entry.serving_options == [
        ("Ollama", "hf.co/org/multi-quant-gguf:Q4_K_M")
    ]


def test_parse_model_gated_repo_has_no_serving_options():
    data = dict(_load("hf_model_qwen3_0_6b.json"))
    data["gated"] = "manual"
    entry = hf.parse_model(data)
    assert entry.serving_options == []
    assert "gated" in entry.tags


def test_parse_model_embedding_and_reranker_categories():
    embedding = _load("hf_search_qwen3.json")[1]
    assert embedding["id"] == "Qwen/Qwen3-Embedding-0.6B"
    entry = hf.parse_model(embedding)
    assert entry.category == "embedding"
    assert entry.capabilities == ["embedding"]
    # Embeddings/rerankers serve through TEI only (HuggingFace), no
    # vLLM or NIM route.
    assert entry.serving_options == [
        ("HuggingFace", "Qwen/Qwen3-Embedding-0.6B")
    ]

    reranker = dict(embedding)
    reranker["id"] = "org/some-reranker"
    reranker["pipeline_tag"] = "text-classification"
    reranker["tags"] = ["rerank-model"]
    entry = hf.parse_model(reranker)
    assert entry.category == "reranker"
    assert entry.capabilities == ["rerank"]


def test_parse_model_category_from_architectures_when_no_pipeline_tag():
    data = {
        "id": "org/causal-only",
        "gated": False,
        "pipeline_tag": None,
        "tags": [],
        "config": {"architectures": ["FooForCausalLM"]},
        "cardData": {},
        "siblings": [],
    }
    entry = hf.parse_model(data)
    assert entry.category == "llm"


def test_parse_model_license_falls_back_to_the_license_tag():
    data = {
        "id": "org/no-card-license",
        "gated": False,
        "pipeline_tag": "text-generation",
        "tags": ["license:mit"],
        "config": {},
        "cardData": {},
        "siblings": [],
    }
    entry = hf.parse_model(data)
    assert entry.license == "mit"


def test_search_builds_the_right_url_and_parameters():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = list(request.url.params.multi_items())
        return httpx.Response(200, json=[])

    results = hf.search(
        "Qwen3", limit=5, transport=httpx.MockTransport(handler)
    )
    assert results == []
    assert captured["url"].startswith(hf.BASE_URL)
    params = dict(captured["params"])
    assert params["search"] == "Qwen3"
    assert params["limit"] == "5"
    expand_values = [v for k, v in captured["params"] if k == "expand[]"]
    assert set(expand_values) == set(hf.SEARCH_EXPAND)


def test_search_parses_every_result():
    payload = [_load("hf_model_qwen3_0_6b.json")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    results = hf.search("q", transport=httpx.MockTransport(handler))
    assert len(results) == 1
    assert results[0].source_id == "Qwen/Qwen3-0.6B"


def test_fetch_requests_blobs_true():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_load("hf_model_qwen3_0_6b.json"))

    entry = hf.fetch("Qwen/Qwen3-0.6B", transport=httpx.MockTransport(handler))
    assert entry.source_id == "Qwen/Qwen3-0.6B"
    assert captured["path"] == "/api/models/Qwen/Qwen3-0.6B"
    assert captured["params"] == {"blobs": "true"}


def test_source_error_on_429_carries_the_retry_after_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, headers={"retry-after": "30"}, text="slow down"
        )

    with pytest.raises(SourceError) as excinfo:
        hf.search("q", transport=httpx.MockTransport(handler))
    assert excinfo.value.status == 429
    assert "30" in excinfo.value.detail


# --- Ollama -------------------------------------------------------------


def test_parse_manifest_qwen3():
    manifest = _load("ollama_manifest_qwen3_0_6b.json")
    entry = ollama.parse_manifest("qwen3", "0.6b", manifest)
    assert entry.source == "ollama"
    assert entry.source_id == "qwen3:0.6b"
    assert entry.name == "qwen3 0.6b"
    assert entry.category == "llm"
    assert entry.capabilities == ["chat"]
    assert entry.formats == ["gguf"]
    assert entry.license is None
    # The application/vnd.ollama.image.model layer's size.
    assert entry.size == 522640096
    assert entry.serving_options == [("Ollama", "qwen3:0.6b")]


@pytest.mark.parametrize("name", list(ollama.EMBEDDING_MODEL_NAMES))
def test_parse_manifest_recognizes_embedding_models(name):
    manifest = _load("ollama_manifest_qwen3_0_6b.json")  # shape only
    entry = ollama.parse_manifest(name, "latest", manifest)
    assert entry.category == "embedding"
    assert entry.capabilities == ["embedding"]


def test_fetch_splits_name_and_tag_and_defaults_to_latest():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(
            200, json=_load("ollama_manifest_qwen3_0_6b.json")
        )

    entry = ollama.fetch("qwen3:0.6b", transport=httpx.MockTransport(handler))
    assert captured["path"] == "/v2/library/qwen3/manifests/0.6b"
    assert entry.source_id == "qwen3:0.6b"

    captured.clear()
    ollama.fetch("qwen3", transport=httpx.MockTransport(handler))
    assert captured["path"] == "/v2/library/qwen3/manifests/latest"


def test_ollama_source_error_on_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "5"}, text="x")

    with pytest.raises(SourceError) as excinfo:
        ollama.fetch("qwen3:0.6b", transport=httpx.MockTransport(handler))
    assert excinfo.value.status == 429
    assert "5" in excinfo.value.detail


# --- OpenRouter -----------------------------------------------------------


def test_parse_model_vision_and_text_only():
    entries = {m["id"]: m for m in _load("openrouter_models.json")["data"]}
    vision = orr.parse_model(entries["openai/gpt-6-astra"])
    assert vision.source == "openrouter"
    assert vision.source_id == "openai/gpt-6-astra"
    assert vision.category == "llm"
    assert "vision" in vision.capabilities
    assert vision.formats == ["hosted"]
    assert vision.serving_options == [("openrouter", "openai/gpt-6-astra")]
    assert "pricing" in vision.raw

    text_only = orr.parse_model(
        entries["inclusionai/ling-3.0-flash-sante:free"]
    )
    assert text_only.capabilities == ["chat"]


def test_list_models_parses_the_data_array():
    payload = _load("openrouter_models.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/models"
        return httpx.Response(200, json=payload)

    entries = orr.list_models(transport=httpx.MockTransport(handler))
    assert len(entries) == len(payload["data"])
    assert {e.source_id for e in entries} == {m["id"] for m in payload["data"]}


def test_openrouter_source_error_on_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "1"}, text="x")

    with pytest.raises(SourceError) as excinfo:
        orr.list_models(transport=httpx.MockTransport(handler))
    assert excinfo.value.status == 429
    assert "1" in excinfo.value.detail


# --- registry.sources dispatch --------------------------------------------


def test_sources_search_dispatches_by_source(monkeypatch):
    monkeypatch.setattr(
        hf, "search", lambda query, limit, **kw: [("hf", query, limit)]
    )
    assert sources.search("huggingface", "qwen", 7) == [("hf", "qwen", 7)]

    monkeypatch.setattr(
        ollama, "fetch", lambda reference, **kw: f"fetched:{reference}"
    )
    assert sources.search("ollama", "qwen3:0.6b", 7) == ["fetched:qwen3:0.6b"]


def test_sources_search_unknown_source_raises():
    with pytest.raises(SourceError) as excinfo:
        sources.search("bogus", "q", 5)
    assert excinfo.value.status == 400


def test_sources_fetch_dispatches_by_source(monkeypatch):
    monkeypatch.setattr(
        hf, "fetch", lambda source_id, **kw: f"hf-fetched:{source_id}"
    )
    assert sources.fetch("huggingface", "org/repo") == "hf-fetched:org/repo"
