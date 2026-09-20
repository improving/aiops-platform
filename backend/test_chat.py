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
from testing.tokens import bearer, make_token
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


def assert_user_id(value: str) -> None:
    """The OpenAI ``user`` field carries the platform user id, never
    the email (``user_key``)."""
    uuid.UUID(value)
    assert "@" not in value


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
    assert_user_id(seen["body"]["user"])


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
    assert_user_id(seen["body"]["user"])


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
    assert_user_id(seen["body"]["user"])


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
    # gpt-4o-mini supports function calling in the price catalog.
    assert targets[litellm_name]["tools"] is True

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
    import api.usage as usage

    monkeypatch.setattr(usage, "get_client", lambda: None)
    assert (
        client.get("/v1alpha1/organizations/current/spend").status_code == 503
    )

    litellm = mock.Mock()
    litellm.team_info.return_value = {
        "spend": 1.5,
        "max_budget": 10.0,
        "budget_reset_at": "2026-10-01T00:00:00Z",
    }
    monkeypatch.setattr(usage, "get_client", lambda: litellm)

    def fake_ensure(db, org, core_v1=None):
        org.litellm_team_id = "t-1"
        return "sk-virtual"

    monkeypatch.setattr(usage, "ensure_org_key", fake_ensure)
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
    import api.usage as usage

    litellm = mock.Mock()
    litellm.team_info.return_value = {
        "spend": 0.0,
        "max_budget": 25.0,
        "budget_reset_at": "2026-10-01T00:00:00Z",
    }
    monkeypatch.setattr(usage, "get_client", lambda: litellm)

    def fake_ensure(db, org, core_v1=None):
        org.litellm_team_id = "t-9"
        return "sk-virtual"

    monkeypatch.setattr(usage, "ensure_org_key", fake_ensure)

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


def test_mock_stream_ends_with_usage_when_asked(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    targets = client.get("/v1alpha1/chat/targets").json()
    assert targets[0]["context_length"] == 4096
    assert targets[0]["tools"] is True

    def chunks(body):
        text = client.post("/v1alpha1/chat/completions", json=body).text
        return [
            json.loads(line[len("data: ") :])
            for line in text.splitlines()
            if line.startswith("data: {")
        ]

    body = {**BODY, "model": "inst-mock", "stream": True}
    assert all("usage" not in c for c in chunks(body))
    last = chunks({**body, "stream_options": {"include_usage": True}})[-1]
    assert last["choices"] == []
    # "You said: hello" is three words; BODY's prompt is one.
    assert last["usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 3,
        "total_tokens": 4,
    }


ECHO_TOOL = {
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Say it again",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
    },
}


def test_mock_calls_a_tool_then_answers_from_its_result(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")

    def chunks(body):
        text = client.post("/v1alpha1/chat/completions", json=body).text
        return [
            json.loads(line[len("data: ") :])
            for line in text.splitlines()
            if line.startswith("data: {")
        ]

    ask = {"role": "user", "content": "call hi there"}
    body = {
        "model": "inst-mock",
        "stream": True,
        "tools": [ECHO_TOOL],
        "messages": [ask],
    }
    first = chunks(body)
    calls = [
        call
        for c in first
        for call in c["choices"][0]["delta"].get("tool_calls", [])
    ]
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "echo"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "message": "hi there"
    }
    assert first[-1]["choices"][0]["finish_reason"] == "tool_calls"

    # The second step of the loop: the tool's result is the last message.
    body["messages"] = [
        ask,
        {"role": "assistant", "content": None, "tool_calls": calls},
        {
            "role": "tool",
            "tool_call_id": calls[0]["id"],
            "content": "hi there",
        },
    ]
    text = "".join(
        c["choices"][0]["delta"].get("content") or "" for c in chunks(body)
    )
    assert text.strip() == "Tool said: hi there"
    # The AI SDK sends an MCP result as the JSON of its content parts.
    body["messages"][-1]["content"] = json.dumps(
        [{"type": "text", "text": "hi there"}]
    )
    text = "".join(
        c["choices"][0]["delta"].get("content") or "" for c in chunks(body)
    )
    assert text.strip() == "Tool said: hi there"

    # Without tools the same words are only text, and without "call"
    # the tools are left alone.
    plain = chunks({**body, "messages": [ask], "tools": []})
    assert "tool_calls" not in json.dumps(plain)
    body["messages"] = [{"role": "user", "content": "hello"}]
    assert "tool_calls" not in json.dumps(chunks(body))


def test_mock_reads_the_system_message_back(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")

    def ask(messages):
        body = {"model": "inst-mock", "messages": messages}
        reply = client.post("/v1alpha1/chat/completions", json=body).json()
        return reply["choices"][0]["message"]["content"]

    question = {"role": "user", "content": "system?"}
    assert ask([question]) == "System: (none)"
    assert ask([{"role": "system", "content": "Be brief."}, question]) == (
        "System: Be brief."
    )


def test_mock_tool_call_without_a_stream(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    body = {
        "model": "inst-mock",
        "tools": [ECHO_TOOL],
        "messages": [{"role": "user", "content": "call hi"}],
    }
    choice = client.post("/v1alpha1/chat/completions", json=body).json()[
        "choices"
    ][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "echo"


def test_instance_context_length_is_the_instances_own_argument():
    from types import SimpleNamespace as NS

    from api.chat import instance_context_length

    default = NS(name="max_model_len", chart_type="llm", defaultValue="16384")
    engine = NS(name="vLLM", default_args=[default])
    model = NS(category="llm")

    def row(args, engine=engine):
        return NS(engine=engine, model=model, config=NS(args=args))

    assert instance_context_length(row({"max_model_len": "4192"})) == 4192
    # Not the engine default: the instance was installed with the default
    # of its day, which the seed no longer says.
    assert instance_context_length(row({})) is None
    assert instance_context_length(row(None)) is None
    assert instance_context_length(row({"max_model_len": "x"})) is None
    # Ollama's served window is not something the platform sets.
    ollama = NS(name="Ollama", default_args=[default])
    assert instance_context_length(row({}, ollama)) is None


def test_instance_tool_calling_reads_the_vllm_flag():
    from types import SimpleNamespace as NS

    from api.chat import instance_tool_calling

    def row(args, engine="vLLM"):
        return NS(engine=NS(name=engine), config=NS(args=args))

    on = {"--enable-auto-tool-choice": "", "--tool-call-parser": "hermes"}
    assert instance_tool_calling(row(on)) is True
    assert instance_tool_calling(row({"max_model_len": "4192"})) is False
    assert instance_tool_calling(row(None)) is False
    assert instance_tool_calling(NS(engine=NS(name="vLLM"), config=None)) is (
        False
    )
    # The platform cannot tell for the other engines: it depends on the
    # model (Ollama) or is not an option at all.
    assert instance_tool_calling(row(on, "Ollama")) is None


def test_create_records_the_vllm_window_on_the_instance():
    from types import SimpleNamespace as NS

    from api.inference_instance import _record_window

    default = NS(name="max_model_len", chart_type="llm", defaultValue="16384")
    vllm = NS(name="vLLM", default_args=[default])
    llm = NS(category="llm")

    config = {"args": None}
    _record_window(config, vllm, llm)
    assert config["args"] == {"max_model_len": "16384"}

    own = {"args": {"max_model_len": "8192", "dtype": "half"}}
    _record_window(own, vllm, llm)
    assert own["args"] == {"max_model_len": "8192", "dtype": "half"}

    other = {"args": {}}
    _record_window(other, NS(name="Ollama", default_args=[default]), llm)
    assert other["args"] == {}
    # A default of another chart type is not this model's.
    _record_window(other, vllm, NS(category="embedding"))
    assert other["args"] == {}


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


def test_litellm_stream_break_becomes_an_error_event(client):
    """A stream cut after the 200 (the gateway's timeout, a dropped
    connection) ends with an OpenAI-style error event and [DONE]."""

    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
            raise httpx.RemoteProtocolError("peer closed connection")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=Broken(),
            headers={"content-type": "text/event-stream"},
        )

    target = _target()
    with (
        mock.patch("api.chat.find_target", return_value=target),
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
    text = response.text
    assert '"content":"hel"' in text
    assert '"type": "stream_error"' in text
    assert "interrupted" in text
    assert text.rstrip().endswith("data: [DONE]")


def test_direct_stream_break_becomes_an_error_event(client):
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
            raise httpx.RemoteProtocolError("peer closed connection")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=Broken(),
            headers={"content-type": "text/event-stream"},
        )

    target = _target(litellm_model_id=None)
    with (
        mock.patch("api.chat.find_target", return_value=target),
        mock.patch("api.chat.litellm_client", return_value=None),
        mock.patch("api.chat.instance_api_key", return_value="k3y"),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions", json={**BODY, "model": TARGET}
        )
    assert response.status_code == 200
    assert '"type": "stream_error"' in response.text
    assert response.text.rstrip().endswith("data: [DONE]")
