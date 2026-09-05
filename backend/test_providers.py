import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from core import create_app
from test_auth import (  # noqa: F401 (fixtures)
    bearer,
    make_token,
    oidc_client,
    rsa_key,
)
from utils import litellm as ll
from utils import secret_store as ss
from utils.gateway import id8
from utils.kubernetes_utils import get_default_namespace

PROVIDERS = "/v1alpha1/providers"


@pytest.fixture(autouse=True)
def secret_store_env(monkeypatch):
    """The fast tier's secret store: an in-process dict, cleared around
    every test so providers from other tests never leak in."""
    monkeypatch.setenv("AIOPS_SECRET_STORE", "memory")
    ss._memory.clear()
    yield
    ss._memory.clear()


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def providers_env(client, monkeypatch):
    """A mocked LiteLLM client returning a fresh model id per
    registration, patched onto api.providers's own seam."""
    litellm = mock.Mock()
    counter = {"n": 0}

    def register(name, params, info):
        counter["n"] += 1
        return f"mid-{counter['n']}"

    litellm.register_model.side_effect = register
    monkeypatch.setattr("api.providers.litellm_client", lambda: litellm)
    return client, litellm


def _name(prefix: str) -> str:
    # Tests share one SQLite file; a per-test suffix avoids 409s between
    # tests that both use, say, "openai".
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create(client, **overrides):
    body = {
        "kind": "openai",
        "name": _name("openai"),
        "api_key": "sk-real",
        "models": ["gpt-4o-mini", "text-embedding-3-small"],
    }
    body.update(overrides)
    return client.post(PROVIDERS, json=body)


# --- discovery ---------------------------------------------------------


def test_discover_mock_mode_returns_canned_models(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    response = client.post(
        f"{PROVIDERS}/discover", json={"kind": "openai", "api_key": "sk-x"}
    )
    assert response.status_code == 200, response.text
    models = response.json()
    assert [m["id"] for m in models] == ["mock-chat-1", "mock-embed-1"]
    assert models[0]["capability"] == "chat"
    assert models[1]["capability"] == "embedding"


def test_discover_unknown_kind_is_400(client):
    response = client.post(
        f"{PROVIDERS}/discover", json={"kind": "bogus", "api_key": "sk-x"}
    )
    assert response.status_code == 400


def test_discover_for_existing_provider_in_mock_mode(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    created = _create(client, name=_name("mock-prov"), models=[])
    assert created.status_code == 201, created.text
    response = client.post(f"{PROVIDERS}/{created.json()['id']}/discover")
    assert response.status_code == 200, response.text
    assert [m["id"] for m in response.json()] == [
        "mock-chat-1",
        "mock-embed-1",
    ]


# --- create --------------------------------------------------------------


def test_create_registers_models_and_hides_the_key(providers_env):
    client, litellm = providers_env
    response = _create(client)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["has_key"] is True
    assert "api_key" not in body
    assert len(body["models"]) == 2
    assert litellm.register_model.call_count == 2

    provider_id8 = body["id"].replace("-", "")[-8:]
    names = [c.args[0] for c in litellm.register_model.call_args_list]
    assert all(n.startswith(f"prov-{provider_id8}/") for n in names)
    params0 = litellm.register_model.call_args_list[0].args[1]
    assert params0["model"] == "openai/gpt-4o-mini"
    assert params0["api_key"] == "sk-real"
    info0 = litellm.register_model.call_args_list[0].args[2]
    assert info0 == {"mode": "chat", "aiops_provider_id": body["id"]}

    listed = client.get(PROVIDERS).json()
    assert any(p["id"] == body["id"] for p in listed)


def test_create_unknown_kind_is_400(providers_env):
    client, _litellm = providers_env
    response = _create(client, kind="bogus", name=_name("bogus"))
    assert response.status_code == 400


def test_create_duplicate_name_is_409(providers_env):
    client, _litellm = providers_env
    name = _name("dup")
    first = _create(client, name=name, models=[])
    assert first.status_code == 201, first.text
    second = _create(client, name=name, models=[])
    assert second.status_code == 409


def test_create_litellm_failure_leaves_no_row_or_secret(providers_env):
    client, litellm = providers_env
    litellm.register_model.side_effect = ll.LiteLLMError("down")
    before = len(client.get(PROVIDERS).json())

    response = _create(client, name=_name("boom"))

    assert response.status_code == 502
    assert len(client.get(PROVIDERS).json()) == before
    assert ss._memory == {}


def test_create_needs_litellm_without_mock(client, monkeypatch):
    monkeypatch.setattr("api.providers.litellm_client", lambda: None)
    response = _create(client, name=_name("no-litellm"))
    assert response.status_code == 503


# --- update ----------------------------------------------------------------


def test_patch_with_new_key_reregisters(providers_env):
    client, litellm = providers_env
    created = _create(client).json()

    response = client.patch(
        f"{PROVIDERS}/{created['id']}", json={"api_key": "sk-new"}
    )

    assert response.status_code == 200, response.text
    assert litellm.register_model.call_count == 4
    new_calls = litellm.register_model.call_args_list[2:]
    assert all(c.args[1]["api_key"] == "sk-new" for c in new_calls)
    assert litellm.delete_model.call_count == 2


def test_patch_litellm_failure_leaves_old_registrations(providers_env):
    client, litellm = providers_env
    created = _create(client).json()
    litellm.register_model.side_effect = ll.LiteLLMError("down")

    response = client.patch(
        f"{PROVIDERS}/{created['id']}", json={"api_key": "sk-new"}
    )

    assert response.status_code == 502
    listed = client.get(PROVIDERS).json()
    provider = next(p for p in listed if p["id"] == created["id"])
    old_names = {m["litellm_model_name"] for m in created["models"]}
    assert {m["litellm_model_name"] for m in provider["models"]} == old_names


# --- delete ------------------------------------------------------------


def test_delete_model_unregisters_one(providers_env):
    client, litellm = providers_env
    created = _create(client).json()
    model_id = created["models"][0]["id"]

    response = client.delete(f"{PROVIDERS}/{created['id']}/models/{model_id}")

    assert response.status_code == 200, response.text
    assert litellm.delete_model.call_count == 1
    listed = client.get(PROVIDERS).json()
    provider = next(p for p in listed if p["id"] == created["id"])
    assert len(provider["models"]) == 1


def test_delete_provider_unregisters_rest_and_deletes_secret(providers_env):
    client, litellm = providers_env
    created = _create(client).json()
    provider_id = created["id"]

    response = client.delete(f"{PROVIDERS}/{provider_id}")

    assert response.status_code == 200, response.text
    assert litellm.delete_model.call_count == 2
    listed = client.get(PROVIDERS).json()
    assert all(p["id"] != provider_id for p in listed)
    secret_name = f"prov-{id8(uuid.UUID(provider_id))}-credentials"
    assert (get_default_namespace(), secret_name) not in ss._memory


# --- authorization -----------------------------------------------------


def test_member_cannot_create_provider(oidc_client, rsa_key):  # noqa: F811
    token = make_token(rsa_key, sub="mallory", roles=("member",))
    response = oidc_client.post(
        PROVIDERS,
        json={"kind": "openai", "name": "x", "api_key": "k", "models": []},
        headers=bearer(token),
    )
    assert response.status_code == 403
