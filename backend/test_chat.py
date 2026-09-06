import json
import uuid
from unittest import mock

import httpx
import pytest
from fastapi.testclient import TestClient

from api.chat import Target, target_labels
from auth.current_user import CurrentUser
from core import create_app
from db.database import get_db_direct
from models.engines import DBEngine
from models.inference_instance import DBInferenceInstance
from models.models import DBModel
from models.organization import Organization
from models.provider import Provider, ProviderModel
from test_auth import (  # noqa: F401 (fixtures)
    bearer,
    make_token,
    oidc_client,
    rsa_key,
)
from utils import litellm as ll
from utils.gateway import id8

INSTANCE = "11111111-2222-4333-8444-555555555555"
TARGET = "inst-23cf13fe"
SETTINGS = ll.LiteLLMSettings(url="https://litellm.test", master_key="sk-m")
BODY = {
    "model": "qwen3:0.6b",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": True,
}
SSE = (
    b'data: {"id":"1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"pong"}}]}\n\n'
    b"data: [DONE]\n\n"
)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def mock_upstream(handler):
    """Patch the direct upstream client with an httpx.MockTransport."""
    return mock.patch(
        "api.chat.upstream_client",
        return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _target(**overrides):
    """A Target for the registered instance TARGET, patched onto
    api.chat.find_target."""
    base = dict(
        kind="instance",
        org_id=None,
        litellm_model_id="mid-1",
        endpoint="https://inf-test.example",
        upstream_model="qwen3:0.6b",
        api_key_lookup=lambda: "k3y",
    )
    base.update(overrides)
    return Target(**base)


def _add_hosted_model(**overrides):
    """A provider with one enabled model in the default organization,
    written directly (test_chat.py has no admin-route helper of its
    own; test_providers.py covers the router)."""
    db = get_db_direct()
    try:
        org = (
            db.query(Organization)
            .filter(Organization.slug == "default")
            .first()
        )
        provider = Provider(
            org_id=org.id,
            kind="openai",
            name=f"openai-{uuid.uuid4().hex[:8]}",
            secret_name="prov-x-credentials",
            enabled=overrides.pop("provider_enabled", True),
        )
        db.add(provider)
        db.flush()
        litellm_name = f"prov-{id8(provider.id)}/gpt-4o-mini"
        model = ProviderModel(
            provider_id=provider.id,
            model="gpt-4o-mini",
            display_name="GPT-4o mini",
            litellm_model_name=litellm_name,
            litellm_model_id="mid-hosted",
            capability="chat",
            enabled=overrides.pop("model_enabled", True),
        )
        db.add(model)
        db.commit()
        return provider.id, litellm_name
    finally:
        db.close()


def test_chat_unknown_target_is_404(client):
    response = client.post(
        "/v1alpha1/chat/completions", json={**BODY, "model": "inst-00000000"}
    )
    assert response.status_code == 404


def test_chat_goes_through_litellm_with_the_org_key(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, content=SSE, headers={"content-type": "text/event-stream"}
        )

    with (
        mock.patch("api.chat.find_target", return_value=_target()),
        mock.patch("api.chat.org_key", return_value="sk-virtual"),
        mock.patch(
            "api.chat.litellm_client",
            return_value=ll.LiteLLMClient(
                SETTINGS, transport=httpx.MockTransport(handler)
            ),
        ),
    ):
        response = client.post(
            "/v1alpha1/chat/completions", json={**BODY, "model": TARGET}
        )
    assert response.status_code == 200
    assert response.content == SSE
    assert seen["url"] == "https://litellm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-virtual"
    assert seen["body"]["model"] == TARGET
    assert seen["body"]["user"] == "dev@example.test"


def test_chat_falls_back_to_the_instance_without_litellm(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(
            200, content=SSE, headers={"content-type": "text/event-stream"}
        )

    target = _target(litellm_model_id=None)
    with (
        mock.patch("api.chat.find_target", return_value=target),
        mock.patch("api.chat.litellm_client", return_value=None),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions", json={**BODY, "model": TARGET}
        )
    assert response.status_code == 200
    assert seen["url"] == "https://inf-test.example/v1/chat/completions"
    assert seen["body"]["model"] == "qwen3:0.6b"
    assert seen["key"] == "k3y"
    assert "user" not in seen["body"]


def test_embeddings_and_rerank_need_litellm(client):
    with (
        mock.patch("api.chat.find_target", return_value=_target()),
        mock.patch("api.chat.litellm_client", return_value=None),
    ):
        assert (
            client.post(
                "/v1alpha1/embeddings", json={"model": TARGET, "input": ["x"]}
            ).status_code
            == 503
        )
        assert (
            client.post(
                "/v1alpha1/rerank",
                json={"model": TARGET, "query": "q", "documents": ["a"]},
            ).status_code
            == 503
        )


def test_embeddings_through_litellm(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": [{"embedding": [0.1, 0.2]}], "usage": {}}
        )

    with (
        mock.patch("api.chat.find_target", return_value=_target()),
        mock.patch("api.chat.org_key", return_value="sk-virtual"),
        mock.patch(
            "api.chat.litellm_client",
            return_value=ll.LiteLLMClient(
                SETTINGS, transport=httpx.MockTransport(handler)
            ),
        ),
    ):
        response = client.post(
            "/v1alpha1/embeddings", json={"model": TARGET, "input": ["x"]}
        )
    assert response.status_code == 200
    assert response.json()["data"][0]["embedding"] == [0.1, 0.2]
    assert seen["body"]["user"] == "dev@example.test"


def test_rerank_through_litellm_carries_the_user(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rerank"
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "rerank-1", "results": []})

    with (
        mock.patch("api.chat.find_target", return_value=_target()),
        mock.patch("api.chat.org_key", return_value="sk-virtual"),
        mock.patch(
            "api.chat.litellm_client",
            return_value=ll.LiteLLMClient(
                SETTINGS, transport=httpx.MockTransport(handler)
            ),
        ),
    ):
        response = client.post(
            "/v1alpha1/rerank",
            json={"model": TARGET, "query": "q", "documents": ["a"]},
        )
    assert response.status_code == 200
    assert seen["body"]["user"] == "dev@example.test"


def test_targets_list_registered_instances(client):
    with mock.patch(
        "api.chat.list_targets",
        return_value=[
            {
                "name": TARGET,
                "label": "Qwen3 · Ollama",
                "capability": "chat",
                "instance_id": INSTANCE,
                "provider_id": None,
                "model": "qwen3:0.6b",
                "engine": "Ollama",
                "ready": True,
                "via": "litellm",
            }
        ],
    ):
        response = client.get("/v1alpha1/chat/targets")
    assert response.status_code == 200
    assert response.json()[0]["name"] == TARGET


# --- hosted provider targets (Phase 2b) -------------------------------


def test_hosted_targets_are_listed_and_resolvable(client):
    provider_id, litellm_name = _add_hosted_model()

    targets = {
        t["name"]: t for t in client.get("/v1alpha1/chat/targets").json()
    }
    assert litellm_name in targets
    assert targets[litellm_name]["provider_id"] == str(provider_id)
    assert targets[litellm_name]["capability"] == "chat"
    assert targets[litellm_name]["instance_id"] is None

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "hi"}}
                ]
            },
        )

    with (
        mock.patch("api.chat.org_key", return_value="sk-virtual"),
        mock.patch(
            "api.chat.litellm_client",
            return_value=ll.LiteLLMClient(
                SETTINGS, transport=httpx.MockTransport(handler)
            ),
        ),
    ):
        response = client.post(
            "/v1alpha1/chat/completions",
            json={**BODY, "model": litellm_name, "stream": False},
        )
    assert response.status_code == 200, response.text
    assert seen["body"]["model"] == litellm_name


def test_disabled_providers_hosted_models_are_not_listed(client):
    _provider_id, litellm_name = _add_hosted_model(provider_enabled=False)
    names = {t["name"] for t in client.get("/v1alpha1/chat/targets").json()}
    assert litellm_name not in names


def test_hosted_target_without_litellm_answers_503(client):
    _provider_id, litellm_name = _add_hosted_model()
    with mock.patch("api.chat.litellm_client", return_value=None):
        response = client.post(
            "/v1alpha1/chat/completions",
            json={**BODY, "model": litellm_name, "stream": False},
        )
    assert response.status_code == 503
    assert "Hosted models need LiteLLM" in response.json()["detail"]


def _admin_user(org_id) -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        sub="dev",
        email="dev@example.test",
        name="Dev",
        org_id=org_id,
        role="admin",
        is_service=False,
    )


def test_target_labels_covers_instances_and_hosted_models(client):
    provider_id, litellm_name = _add_hosted_model()

    db = get_db_direct()
    try:
        org = (
            db.query(Organization)
            .filter(Organization.slug == "default")
            .first()
        )
        model = db.query(DBModel).first()
        engine = db.query(DBEngine).first()
        instance = DBInferenceInstance(
            model_id=model.id,
            engine_id=engine.id,
            org_id=org.id,
            litellm_model_name="inst-abcdef12",
        )
        db.add(instance)
        db.commit()
        model_name, engine_name = model.name, engine.name
        provider_name = (
            db.query(Provider).filter(Provider.id == provider_id).first().name
        )

        labels = target_labels(db, _admin_user(org.id))
        # Written directly, not through the router: clean it up here so it
        # does not linger as an instance no controller/credential owns,
        # which later list_inference_instances calls would try to poll.
        db.delete(instance)
        db.commit()
    finally:
        db.close()

    assert labels["inst-abcdef12"] == f"{model_name} · {engine_name}"
    assert labels[litellm_name] == f"GPT-4o mini · {provider_name}"


def test_org_spend_endpoint(client, monkeypatch):
    import api.organizations as orgs

    monkeypatch.setattr(orgs, "get_client", lambda: None)
    assert (
        client.get("/v1alpha1/organizations/current/spend").status_code == 503
    )

    litellm = mock.Mock()
    litellm.team_info.return_value = {
        "spend": 1.5,
        "max_budget": 10.0,
        "budget_reset_at": "2026-10-01T00:00:00Z",
    }
    monkeypatch.setattr(orgs, "get_client", lambda: litellm)

    def fake_ensure(db, org, core_v1=None):
        org.litellm_team_id = "t-1"
        return "sk-virtual"

    monkeypatch.setattr(orgs, "ensure_org_key", fake_ensure)
    response = client.get("/v1alpha1/organizations/current/spend")
    assert response.status_code == 200
    assert response.json() == {
        "team_id": "t-1",
        "spend": 1.5,
        "max_budget": 10.0,
        "budget_reset_at": "2026-10-01T00:00:00Z",
        "budget_usd": None,
    }

    litellm.team_info.side_effect = ll.LiteLLMError("down")
    assert (
        client.get("/v1alpha1/organizations/current/spend").status_code == 502
    )


def test_put_budget_calls_update_team_budget_and_persists(client, monkeypatch):
    import api.organizations as orgs

    litellm = mock.Mock()
    litellm.team_info.return_value = {
        "spend": 0.0,
        "max_budget": 25.0,
        "budget_reset_at": "2026-10-01T00:00:00Z",
    }
    monkeypatch.setattr(orgs, "get_client", lambda: litellm)

    def fake_ensure(db, org, core_v1=None):
        org.litellm_team_id = "t-9"
        return "sk-virtual"

    monkeypatch.setattr(orgs, "ensure_org_key", fake_ensure)

    response = client.put(
        "/v1alpha1/organizations/current/budget", json={"budget_usd": 25.0}
    )
    assert response.status_code == 200, response.text
    assert response.json()["budget_usd"] == 25.0
    litellm.update_team_budget.assert_called_once_with("t-9", 25.0)

    spend = client.get("/v1alpha1/organizations/current/spend").json()
    assert spend["budget_usd"] == 25.0


def test_put_budget_needs_admin(oidc_client, rsa_key):  # noqa: F811
    token = make_token(rsa_key, sub="member-a", roles=("member",))
    response = oidc_client.put(
        "/v1alpha1/organizations/current/budget",
        json={"budget_usd": 5.0},
        headers=bearer(token),
    )
    assert response.status_code == 403


def test_mock_mode_serves_targets_chat_embeddings_rerank(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    targets = client.get("/v1alpha1/chat/targets").json()
    assert targets[0]["name"] == "inst-mock"
    chat = client.post(
        "/v1alpha1/chat/completions",
        json={**BODY, "model": "inst-mock", "stream": False},
    ).json()
    assert chat["choices"][0]["message"]["content"] == "You said: hello"
    emb = client.post(
        "/v1alpha1/embeddings",
        json={"model": "inst-mock", "input": ["a", "b"]},
    ).json()
    assert len(emb["data"]) == 2 and len(emb["data"][0]["embedding"]) == 4
    rr = client.post(
        "/v1alpha1/rerank",
        json={"model": "inst-mock", "query": "q", "documents": ["a", "b"]},
    ).json()
    assert [r["index"] for r in rr["results"]] == [1, 0]


def test_chat_forwards_upstream_errors(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    target = _target(litellm_model_id=None)
    with (
        mock.patch("api.chat.find_target", return_value=target),
        mock.patch("api.chat.litellm_client", return_value=None),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions", json={**BODY, "model": TARGET}
        )
    assert response.status_code == 404
    assert "model not found" in response.json()["detail"]


def test_chat_unreachable_upstream_is_502(client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    target = _target(litellm_model_id=None, api_key_lookup=lambda: None)
    with (
        mock.patch("api.chat.find_target", return_value=target),
        mock.patch("api.chat.litellm_client", return_value=None),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions", json={**BODY, "model": TARGET}
        )
    assert response.status_code == 502


def test_chat_returns_json_without_stream(client):
    answer = {
        "choices": [{"message": {"role": "assistant", "content": "pong"}}]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") is None
        return httpx.Response(200, json=answer)

    target = _target(litellm_model_id=None, api_key_lookup=lambda: None)
    with (
        mock.patch("api.chat.find_target", return_value=target),
        mock.patch("api.chat.litellm_client", return_value=None),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions",
            json={**BODY, "model": TARGET, "stream": False},
        )
    assert response.status_code == 200
    assert response.json() == answer


def test_chat_mock_mode_echoes_the_last_user_message(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    response = client.post(
        "/v1alpha1/chat/completions", json={**BODY, "model": "inst-mock"}
    )
    assert response.status_code == 200
    # One SSE chunk per word: join the deltas before asserting.
    deltas = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    text = "".join(d["choices"][0]["delta"].get("content", "") for d in deltas)
    assert text.strip() == "You said: hello"
    assert response.text.rstrip().endswith("data: [DONE]")

    response = client.post(
        "/v1alpha1/chat/completions",
        json={**BODY, "model": "inst-mock", "stream": False},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "You said: hello"
