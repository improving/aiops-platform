"""utils/langflow.py: settings, the client, and provisioning.

Langflow is an httpx.MockTransport handler; nothing here touches the
network. Provisioning writes OPENAI_COMPATIBLE_BASE_URL before
OPENAI_COMPATIBLE_API_KEY, because Langflow checks the key by listing
<base URL>/models with it, and a second run updates in place.
"""

import json
from unittest import mock

import httpx
import pytest

from schemas.langflow import LangflowProvisionSchema
from utils import langflow as lf


def test_settings_need_the_api_url(monkeypatch):
    monkeypatch.delenv("LANGFLOW_API_URL", raising=False)
    assert lf.langflow_settings() is None
    monkeypatch.setenv("LANGFLOW_API_URL", "https://langflow.test/")
    monkeypatch.setenv("LITELLM_URL", "https://litellm.test")
    monkeypatch.delenv("LITELLM_CLUSTER_URL", raising=False)
    settings = lf.langflow_settings()
    assert settings.api_url == "https://langflow.test"
    # The in-cluster address defaults to the one the backend uses itself.
    assert settings.litellm_cluster_url == "https://litellm.test"
    monkeypatch.setenv(
        "LITELLM_CLUSTER_URL", "http://litellm.litellm.svc:4000/"
    )
    assert (
        lf.langflow_settings().litellm_cluster_url
        == "http://litellm.litellm.svc:4000"
    )


class FakeLangflow:
    """Enough of Langflow's variables API to provision against."""

    def __init__(self, *, key_write_fails=False):
        self.variables = []
        self.calls = []
        self.posted = []  # raw POST bodies, value included
        self.key_write_fails = key_write_fails

    def handler(self, request):
        path = request.url.path
        self.calls.append((request.method, path))
        assert request.headers["Authorization"] == "Bearer platform-token"
        if path == "/api/v1/users/whoami":
            return httpx.Response(
                200, json={"username": "alice", "is_superuser": False}
            )
        if path == "/api/v1/variables/" and request.method == "GET":
            return httpx.Response(200, json=self.variables)
        if path == "/api/v1/variables/" and request.method == "POST":
            body = json.loads(request.content)
            self.posted.append(body)
            if body["name"] == lf.API_KEY_VAR and self.key_write_fails:
                return httpx.Response(
                    400,
                    json={
                        "detail": (
                            "Authentication failed for the OpenAI-compatible"
                            " endpoint. Check OPENAI_COMPATIBLE_API_KEY."
                        )
                    },
                )
            row = {"id": f"id-{len(self.variables)}", **body, "value": None}
            self.variables.append(row)
            return httpx.Response(201, json=row)
        if path.startswith("/api/v1/variables/") and request.method == "PATCH":
            body = json.loads(request.content)
            wanted = path.rsplit("/", 1)[1]
            row = next(v for v in self.variables if v["id"] == wanted)
            row.update({k: v for k, v in body.items() if k != "value"})
            return httpx.Response(200, json=row)
        return httpx.Response(404, json={"detail": path})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LANGFLOW_API_URL", "https://langflow.test")
    monkeypatch.setenv("LITELLM_URL", "https://litellm.test")
    monkeypatch.setenv(
        "LITELLM_CLUSTER_URL", "http://litellm.litellm.svc:4000"
    )


def _targets():
    return [
        {
            "name": "prov-1/gpt-4o-mini",
            "label": "GPT-4o mini · OpenAI",
            "capability": "chat",
            "ready": True,
            "instance_id": None,
            "provider_id": "p1",
        },
        {
            "name": "inst-1234abcd",
            "label": "Qwen · Ollama",
            "capability": "chat",
            "ready": True,
            "instance_id": "i1",
            "provider_id": None,
        },
    ]


def _models():
    return [{"name": t["name"], "label": t["label"]} for t in _targets()]


ALICE = mock.Mock(sub="alice", org_id="org-1")


def _provision(langflow, models=None):
    db = mock.Mock()
    db.get.return_value.name = "Acme"
    with mock.patch.object(
        lf, "ensure_user_key", return_value="sk-alice"
    ) as ensure_user_key:
        result = lf.provision_openai_compatible(
            db,
            ALICE,
            "platform-token",
            _models() if models is None else models,
            transport=httpx.MockTransport(langflow.handler),
        )
    # The member's own key, never the organization's shared one: a flow
    # calls LiteLLM with no `user` field, so only the key says who spent.
    ensure_user_key.assert_called_once_with(
        db, db.get.return_value, ALICE, None
    )
    return result


def test_provisioning_writes_base_url_then_key(env):
    langflow = FakeLangflow()
    result = _provision(langflow)
    assert [v["name"] for v in langflow.variables] == [
        lf.BASE_URL_VAR,
        lf.API_KEY_VAR,
    ]
    base, key = langflow.variables
    assert base["type"] == "Generic"
    assert base["default_fields"] == ["openai_compatible_base_url"]
    assert key["type"] == "Credential"
    assert key["default_fields"] == ["api_key"]
    assert result.langflow_user == "alice"
    assert result.organization == "Acme"
    assert [m.name for m in result.models] == [
        "prov-1/gpt-4o-mini",
        "inst-1234abcd",
    ]
    # What was sent, value included: the in-cluster LiteLLM plus /v1
    # (the bundle's base_url_suffix), and the member's key.
    assert langflow.posted[0]["value"] == "http://litellm.litellm.svc:4000/v1"
    assert langflow.posted[1]["value"] == "sk-alice"


def test_mcp_variables_need_the_backend_address_and_a_writer(env, monkeypatch):
    # Without AIOPS_BACKEND_CLUSTER_URL: as before, two variables.
    langflow = FakeLangflow()
    _provision(langflow)
    assert len(langflow.variables) == 2

    monkeypatch.setenv(
        "AIOPS_BACKEND_CLUSTER_URL", "http://aiops-backend.ai-stack.svc:8000/"
    )
    seen = []

    def managed(db, **kwargs):
        seen.append(kwargs)
        return None if kwargs["holder_has_it"] else "aiops_abcd1234_secret"

    monkeypatch.setattr(lf, "ensure_managed_token", managed)
    ALICE.role = "member"
    langflow = FakeLangflow()
    _provision(langflow)
    by_name = {v["name"]: v for v in langflow.posted}
    assert by_name[lf.MCP_URL_VAR]["value"] == (
        "http://aiops-backend.ai-stack.svc:8000/v1alpha1/mcp"
    )
    assert by_name[lf.MCP_TOKEN_VAR]["value"] == "aiops_abcd1234_secret"
    assert by_name[lf.MCP_TOKEN_VAR]["type"] == "Credential"
    assert seen[0]["scope"] == "mcp" and seen[0]["name"] == "langflow"
    assert seen[0]["holder_has_it"] is False

    # The next page load: Langflow has the variable, no new token, and
    # the stored one is not written over.
    posted = len(langflow.posted)
    _provision(langflow)
    assert seen[1]["holder_has_it"] is True
    assert len(langflow.posted) == posted
    assert ("PATCH", "/api/v1/variables/id-3") not in langflow.calls

    # A viewer cannot use the endpoint, so gets no way to it.
    ALICE.role = "viewer"
    langflow = FakeLangflow()
    _provision(langflow)
    assert len(langflow.variables) == 2
    ALICE.role = "member"


def test_a_second_run_updates_in_place(env):
    langflow = FakeLangflow()
    langflow.variables = [
        {
            "id": "b",
            "name": lf.BASE_URL_VAR,
            "type": "Generic",
            "default_fields": [],
            "value": None,
        },
        {
            "id": "k",
            "name": lf.API_KEY_VAR,
            "type": "Credential",
            "default_fields": ["api_key"],
            "value": None,
        },
    ]
    _provision(langflow)
    writes = [c for c in langflow.calls if c[0] in ("POST", "PATCH")]
    assert writes == [
        ("PATCH", "/api/v1/variables/b"),
        ("PATCH", "/api/v1/variables/k"),
    ]
    # The type travels with the update, so a slot someone retyped by
    # hand comes back to what the provider expects.
    assert langflow.variables[0]["type"] == "Generic"
    assert langflow.variables[1]["type"] == "Credential"


def test_langflows_refusal_is_surfaced_with_its_detail(env):
    langflow = FakeLangflow(key_write_fails=True)
    with pytest.raises(lf.LangflowError) as raised:
        _provision(langflow)
    assert raised.value.status == 400
    assert "OPENAI_COMPATIBLE_API_KEY" in raised.value.detail
    # The base URL was still written: the next run only has the key to fix.
    assert [v["name"] for v in langflow.variables] == [lf.BASE_URL_VAR]


def test_unreachable_langflow_is_a_langflow_error(env):
    def down(request):
        raise httpx.ConnectError("refused")

    with (
        mock.patch.object(lf, "ensure_user_key", return_value="sk-alice"),
        pytest.raises(lf.LangflowError) as raised,
    ):
        lf.provision_openai_compatible(
            mock.Mock(),
            mock.Mock(sub="alice", org_id="org-1"),
            "platform-token",
            [],
            transport=httpx.MockTransport(down),
        )
    assert raised.value.status is None
    assert "unreachable" in raised.value.detail


def test_provisioning_needs_a_litellm_address(monkeypatch):
    # LANGFLOW_API_URL alone is not enough: the base URL would be "/v1".
    monkeypatch.setenv("LANGFLOW_API_URL", "https://langflow.test")
    monkeypatch.delenv("LITELLM_URL", raising=False)
    monkeypatch.delenv("LITELLM_CLUSTER_URL", raising=False)
    with pytest.raises(lf.LangflowError) as raised:
        lf.provision_openai_compatible(
            mock.Mock(), mock.Mock(org_id="org-1"), "platform-token", []
        )
    assert "LITELLM_URL" in raised.value.detail


def test_provision_endpoint_needs_a_browser_session(
    oidc_client, tokens, monkeypatch
):
    # Checked before LiteLLM: a token caller must hear this whatever
    # LiteLLM's state.
    monkeypatch.setenv("LANGFLOW_API_URL", "https://langflow.test")
    created = oidc_client.post(
        "/v1alpha1/tokens",
        json={"name": "x", "scope": "write"},
        headers=tokens["alice"],
    )
    secret = created.json()["token"]
    response = oidc_client.post(
        "/v1alpha1/langflow/provision",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 409
    assert "browser" in response.json()["detail"]


def test_provision_endpoint_is_503_without_langflow(
    oidc_client, tokens, monkeypatch
):
    monkeypatch.delenv("LANGFLOW_API_URL", raising=False)
    response = oidc_client.post(
        "/v1alpha1/langflow/provision", headers=tokens["alice"]
    )
    assert response.status_code == 503


def test_provision_endpoint_forwards_the_callers_bearer(
    oidc_client, tokens, monkeypatch
):
    monkeypatch.setenv("LANGFLOW_API_URL", "https://langflow.test")
    seen = {}

    def fake(db, user, bearer, models, **kwargs):
        seen["bearer"] = bearer
        seen["models"] = models
        return LangflowProvisionSchema(
            langflow_user="alice", organization="Default", models=[]
        )

    with (
        mock.patch("api.langflow.provision_openai_compatible", fake),
        mock.patch("api.langflow.get_client", return_value=object()),
        mock.patch(
            "api.langflow.list_targets", return_value=_targets()
        ) as listed,
    ):
        response = oidc_client.post(
            "/v1alpha1/langflow/provision", headers=tokens["alice"]
        )
    assert response.status_code == 200, response.text
    expected = tokens["alice"]["Authorization"].removeprefix("Bearer ")
    assert seen["bearer"] == expected
    assert response.json()["langflow_user"] == "alice"
    # Names and labels only, and no pod probe on a page load.
    assert seen["models"] == _models()
    assert listed.call_args.kwargs == {"probe": False}


def test_provision_endpoint_relays_langflows_detail(
    oidc_client, tokens, monkeypatch
):
    monkeypatch.setenv("LANGFLOW_API_URL", "https://langflow.test")
    with (
        mock.patch(
            "api.langflow.provision_openai_compatible",
            side_effect=lf.LangflowError(
                "Langflow answered 400: Authentication failed", 400
            ),
        ),
        mock.patch("api.langflow.get_client", return_value=object()),
    ):
        response = oidc_client.post(
            "/v1alpha1/langflow/provision", headers=tokens["alice"]
        )
    assert response.status_code == 502
    assert "Authentication failed" in response.json()["detail"]


def test_provision_endpoint_relays_a_litellm_failure_as_502(
    oidc_client, tokens, monkeypatch
):
    monkeypatch.setenv("LANGFLOW_API_URL", "https://langflow.test")
    from utils.litellm import LiteLLMError

    with (
        mock.patch(
            "api.langflow.provision_openai_compatible",
            side_effect=LiteLLMError("LiteLLM unreachable: refused"),
        ),
        mock.patch("api.langflow.get_client", return_value=object()),
    ):
        response = oidc_client.post(
            "/v1alpha1/langflow/provision", headers=tokens["alice"]
        )
    assert response.status_code == 502
    assert "LiteLLM" in response.json()["detail"]


def test_provision_endpoint_mock(monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    from fastapi.testclient import TestClient

    from core import create_app

    client = TestClient(create_app())
    response = client.post("/v1alpha1/langflow/provision")
    assert response.status_code == 200
    assert response.json()["models"][0]["name"] == "inst-mock"
