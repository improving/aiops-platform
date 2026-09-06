import json
import uuid
from datetime import datetime
from unittest import mock

import httpx
import pytest
from kubernetes.client.exceptions import ApiException

from utils import litellm as ll

SETTINGS = ll.LiteLLMSettings(url="https://litellm.test", master_key="sk-m")


def test_settings_need_both_env_vars(monkeypatch):
    monkeypatch.delenv("LITELLM_URL", raising=False)
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    assert ll.litellm_settings() is None
    monkeypatch.setenv("LITELLM_URL", "https://litellm.test/")
    assert ll.litellm_settings() is None
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-m")
    assert ll.litellm_settings() == SETTINGS  # trailing slash dropped


def test_instance_model_name_uses_id8():
    instance_id = uuid.UUID("293534ae-2e76-48c9-99b6-a60f23cf13fe")
    assert ll.instance_model_name(instance_id) == "inst-23cf13fe"


def test_hosted_model_name_keeps_slashes_in_the_model_id():
    provider_id = uuid.UUID("293534ae-2e76-48c9-99b6-a60f23cf13fe")
    # OpenRouter ids already carry a "/"; the id8 prefix is still the
    # only separator a caller should split on.
    assert (
        ll.hosted_model_name(provider_id, "openai/gpt-4o-mini")
        == "prov-23cf13fe/openai/gpt-4o-mini"
    )


def test_hosted_litellm_params():
    provider_id = uuid.UUID("293534ae-2e76-48c9-99b6-a60f23cf13fe")
    params, info = ll.hosted_litellm_params(
        provider_id, "openai", "gpt-4o-mini", "chat", "sk-x", None
    )
    assert params == {"model": "openai/gpt-4o-mini", "api_key": "sk-x"}
    assert info == {
        "mode": "chat",
        "aiops_provider_id": str(provider_id),
    }

    params, _ = ll.hosted_litellm_params(
        provider_id,
        "openai",
        "gpt-4o-mini",
        "chat",
        None,
        "https://proxy.example/v1",
    )
    assert "api_key" not in params
    assert params["api_base"] == "https://proxy.example/v1"


@pytest.mark.parametrize(
    ("engine", "category", "expected_model", "expected_base", "mode"),
    [
        ("Ollama", "llm", "openai/qwen3:0.6b", "http://svc:80/v1", "chat"),
        ("vLLM", "llm", "openai/qwen3:0.6b", "http://svc:80/v1", "chat"),
        (
            "HuggingFace",
            "llm",
            "openai/qwen3:0.6b",
            "http://svc:80/v1",
            "chat",
        ),
        ("NIM", "llm", "openai/qwen3:0.6b", "http://svc:80/v1", "chat"),
        (
            "Ollama",
            "embedding",
            "openai/qwen3:0.6b",
            "http://svc:80/v1",
            "embedding",
        ),
        (
            "HuggingFace",
            "embedding",
            "huggingface/qwen3:0.6b",
            "http://svc:80",
            "embedding",
        ),
        (
            "NIM",
            "embedding",
            "openai/qwen3:0.6b",
            "http://svc:80/v1",
            "embedding",
        ),
        (
            "HuggingFace",
            "reranker",
            "huggingface/qwen3:0.6b",
            "http://svc:80",
            "rerank",
        ),
    ],
)
def test_instance_litellm_params(
    engine, category, expected_model, expected_base, mode
):
    params, info = ll.instance_litellm_params(
        engine, category, "qwen3:0.6b", "http://svc:80", "k3y"
    )
    assert params == {
        "model": expected_model,
        "api_base": expected_base,
        "api_key": "k3y",
    }
    assert info["mode"] == mode


def test_instance_litellm_params_unsupported_pairs():
    assert (
        ll.instance_litellm_params(
            "NIM", "reranker", "m", "http://svc:80", None
        )
        is None
    )
    assert (
        ll.instance_litellm_params(
            "OPEA", "prompt_guard", "m", "http://svc:80", None
        )
        is None
    )
    params, _ = ll.instance_litellm_params(
        "Ollama", "llm", "m", "http://svc:80", None
    )
    assert "api_key" not in params


def _client(handler):
    return ll.LiteLLMClient(SETTINGS, transport=httpx.MockTransport(handler))


def test_register_and_delete_model():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (request.method, request.url.path, json.loads(request.content))
        )
        assert request.headers["authorization"] == "Bearer sk-m"
        if request.url.path == "/model/new":
            return httpx.Response(
                200, json={"model_id": "mid-1", "model_name": "inst-1"}
            )
        if request.url.path == "/model/delete":
            return httpx.Response(200, json={"message": "deleted"})
        return httpx.Response(404)

    client = _client(handler)
    assert (
        client.register_model(
            "inst-1", {"model": "openai/x"}, {"mode": "chat"}
        )
        == "mid-1"
    )
    client.delete_model("mid-1")
    assert calls[0] == (
        "POST",
        "/model/new",
        {
            "model_name": "inst-1",
            "litellm_params": {"model": "openai/x"},
            "model_info": {"mode": "chat"},
        },
    )
    assert calls[1] == ("POST", "/model/delete", {"id": "mid-1"})


def test_team_and_key_lifecycle():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.url.path == "/team/new":
            assert (
                body["team_alias"] == "org-default"
                and body["max_budget"] == 10
            )
            return httpx.Response(
                200,
                json={
                    "team_id": "t-1",
                    "team_alias": "org-default",
                    "max_budget": 10.0,
                    "spend": 0.0,
                },
            )
        if request.url.path == "/key/generate":
            assert body["team_id"] == "t-1"
            return httpx.Response(
                200,
                json={
                    "key": "sk-virtual",
                    "team_id": "t-1",
                    "key_alias": body["key_alias"],
                },
            )
        if request.url.path == "/team/info":
            assert request.url.params["team_id"] == "t-1"
            return httpx.Response(
                200,
                json={
                    "team_info": {
                        "team_id": "t-1",
                        "spend": 1.5,
                        "max_budget": 10.0,
                    },
                    "keys": [],
                },
            )
        if request.url.path == "/key/delete":
            assert body == {"keys": ["sk-virtual"]}
            return httpx.Response(200, json={"deleted_keys": ["sk-virtual"]})
        if request.url.path == "/team/delete":
            assert body == {"team_ids": ["t-1"]}
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = _client(handler)
    assert (
        client.create_team("org-default", {"aiops_org": "x"}, max_budget=10)
        == "t-1"
    )
    assert (
        client.generate_key("t-1", "org-default-chat", {"aiops_org": "x"})
        == "sk-virtual"
    )
    assert client.team_info("t-1")["spend"] == 1.5
    client.delete_key("sk-virtual")
    client.delete_team("t-1")


def test_update_team_budget():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"team_id": "t-1"})

    client = _client(handler)
    client.update_team_budget("t-1", 25.0)
    client.update_team_budget("t-1", None)

    assert calls[0] == {
        "team_id": "t-1",
        "max_budget": 25.0,
        "budget_duration": "30d",
    }
    assert calls[1] == {
        "team_id": "t-1",
        "max_budget": None,
        "budget_duration": "30d",
    }


def test_spend_logs_pages_until_the_last_page():
    seen_pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        seen_pages.append(page)
        assert request.url.params["team_id"] == "t-1"
        assert request.url.params["start_date"] == "2026-09-01 00:00:00"
        assert request.url.params["end_date"] == "2026-09-07 00:00:00"
        assert request.url.params["page_size"] == "500"
        if page == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"request_id": "r1"}],
                    "total_pages": 2,
                    "total_is_capped": False,
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [{"request_id": "r2"}],
                "total_pages": 2,
                "total_is_capped": False,
            },
        )

    client = _client(handler)
    rows, capped = client.spend_logs(
        "t-1",
        datetime(2026, 9, 1),
        datetime(2026, 9, 7),
    )
    assert seen_pages == [1, 2]
    assert [r["request_id"] for r in rows] == ["r1", "r2"]
    assert capped is False


def test_spend_logs_filters_by_end_user_only_when_asked():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("end_user"))
        return httpx.Response(
            200,
            json={"data": [], "total_pages": 1, "total_is_capped": False},
        )

    client = _client(handler)
    client.spend_logs("t-1", datetime(2026, 9, 1), datetime(2026, 9, 7))
    client.spend_logs(
        "t-1", datetime(2026, 9, 1), datetime(2026, 9, 7), end_user="u-1"
    )
    assert seen == [None, "u-1"]


def test_spend_logs_stops_at_the_page_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "data": [{"request_id": f"r{page}"}],
                "total_pages": 999,
                "total_is_capped": False,
            },
        )

    client = _client(handler)
    rows, capped = client.spend_logs(
        "t-1", datetime(2026, 9, 1), datetime(2026, 9, 7)
    )
    assert len(rows) == ll.SPEND_LOGS_MAX_PAGES
    assert capped is True


def test_spend_logs_reports_total_is_capped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"request_id": "r1"}],
                "total_pages": 1,
                "total_is_capped": True,
            },
        )

    client = _client(handler)
    rows, capped = client.spend_logs(
        "t-1", datetime(2026, 9, 1), datetime(2026, 9, 7)
    )
    assert len(rows) == 1
    assert capped is True


def test_errors_raise_litellm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ll.LiteLLMError) as excinfo:
        _client(handler).register_model("x", {}, {})
    assert "500" in str(excinfo.value)


def test_get_client_is_none_without_settings(monkeypatch):
    monkeypatch.delenv("LITELLM_URL", raising=False)
    assert ll.get_client() is None


def test_ensure_org_key_creates_team_key_and_secret(monkeypatch):
    from sqlalchemy.orm import Session

    from models.organization import Organization

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/team/new":
            return httpx.Response(200, json={"team_id": "t-9"})
        if request.url.path == "/key/generate":
            return httpx.Response(200, json={"key": "sk-org"})
        return httpx.Response(404)

    monkeypatch.setattr(ll, "get_client", lambda: _client(handler))
    secrets = {}
    core_v1 = mock.Mock()
    core_v1.read_namespaced_secret.side_effect = lambda name, namespace: (
        _ for _ in ()
    ).throw(ApiException(status=404))
    core_v1.create_namespaced_secret.side_effect = lambda namespace, body: (
        secrets.update({body.metadata.name: body.string_data})
    )
    db = mock.Mock(spec=Session)
    org = Organization(
        id=uuid.UUID("de5a0170-0000-4000-8000-000000000001"),
        slug="default",
        name="Default",
    )
    ll._org_key_cache.clear()
    assert ll.ensure_org_key(db, org, core_v1) == "sk-org"
    assert org.litellm_team_id == "t-9"
    assert org.litellm_key_secret_name == "org-00000001-litellm-key"
    assert secrets["org-00000001-litellm-key"] == {"key": "sk-org"}
    assert calls[0][1]["team_alias"] == "org-default"
    db.commit.assert_called()
    # Second call: cached, no proxy round trip.
    assert ll.ensure_org_key(db, org, core_v1) == "sk-org"
    assert len(calls) == 2
