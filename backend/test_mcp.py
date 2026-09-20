"""MCP servers (api/mcp.py): the registry, the LiteLLM registration and
the /v1alpha1/mcp endpoint. LiteLLM is a mock on this module's own
seam; the secret store is the in-process one."""

import json
import uuid
from unittest import mock

import httpx
import pytest
from fastapi.testclient import TestClient

from core import create_app
from utils import litellm as ll
from utils import mcp as mcp_utils
from utils import secret_store as ss
from utils.gateway import id8
from utils.kubernetes_utils import get_default_namespace

SERVERS = "/v1alpha1/mcp/servers"
ENDPOINT = "/v1alpha1/mcp"
URL = "https://mcp.example.com/mcp"
TOOLS = [
    {
        "name": "search_issues",
        "description": "Search issues",
        "annotations": {"readOnlyHint": True},
    },
    {"name": "create_issue", "description": "Create an issue"},
]
ALICE = {"X-Dev-User": "alice"}
VIEWER = {"X-Dev-User": "viewer"}
OUTSIDER = {"X-Dev-User": "outsider"}


@pytest.fixture(autouse=True)
def secret_store_env(monkeypatch):
    monkeypatch.setenv("AIOPS_SECRET_STORE", "memory")
    ss._memory.clear()
    yield
    ss._memory.clear()


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """No network in the tests: every name resolves to a public
    address unless a test says otherwise."""
    monkeypatch.setattr(mcp_utils, "_resolve", lambda host: ["93.184.216.34"])


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def env(client, monkeypatch):
    """A mocked LiteLLM client on api.mcp's seam, and an organization
    key that needs no cluster."""
    litellm = mock.Mock()
    litellm.list_mcp_tools.return_value = TOOLS
    litellm.register_mcp_server.side_effect = lambda body: (
        f"srv-{uuid.uuid4().hex[:6]}"
    )
    monkeypatch.setattr("api.mcp.litellm_client", lambda: litellm)
    monkeypatch.setattr("api.mcp.org_key", lambda db, user: "sk-org")
    monkeypatch.setattr("api.mcp._team_id", lambda litellm, db, user: "team-1")
    return client, litellm


def _name() -> str:
    return f"github_{uuid.uuid4().hex[:6]}"


def _create(client, **overrides):
    body = {
        "name": _name(),
        "url": URL,
        "transport": "http",
        "credential": {"auth_type": "bearer", "value": "ghp_secret"},
    }
    body.update(overrides)
    return client.post(SERVERS, json=body)


# --- the URL rule ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example.com/mcp",
        "ftp://mcp.example.com/mcp",
        "https://localhost/mcp",
        "https://127.0.0.1/mcp",
        "https://10.0.0.8/mcp",
        "https://169.254.169.254/latest",
        "https://litellm.litellm.svc/mcp",
        "https://litellm.litellm.svc.cluster.local/mcp",
        "https://user:pw@mcp.example.com/mcp",
        "https:///mcp",
    ],
)
def test_url_rule_refuses(url):
    with pytest.raises(mcp_utils.McpUrlError):
        mcp_utils.validate_server_url(url)


def test_url_rule_refuses_a_public_name_with_a_private_address(monkeypatch):
    monkeypatch.setattr(mcp_utils, "_resolve", lambda host: ["10.1.2.3"])
    with pytest.raises(mcp_utils.McpUrlError):
        mcp_utils.validate_server_url(URL)


def test_url_rule_accepts_public_https_and_a_listed_dev_host(monkeypatch):
    assert mcp_utils.validate_server_url(f" {URL} ") == URL
    dev = "http://mcp-test.mcp-test.svc.cluster.local:8000/mcp"
    with pytest.raises(mcp_utils.McpUrlError):
        mcp_utils.validate_server_url(dev)
    monkeypatch.setenv(
        "AIOPS_MCP_ALLOW_INSECURE_HOSTS",
        "mcp-test.mcp-test.svc.cluster.local",
    )
    assert mcp_utils.validate_server_url(dev) == dev


def test_alias_is_unique_and_safe_in_a_tool_name_and_a_header_name():
    server = uuid.uuid4()
    alias = mcp_utils.litellm_alias(server, "git_hub")
    assert alias == f"github{id8(server)}"
    # No "-" (the first one ends the alias in a tool name) and no "_"
    # (Envoy refuses it in x-mcp-<alias>-authorization).
    assert alias.isalnum()
    assert mcp_utils.valid_name("git_hub")
    for bad in ("GitHub", "git-hub", "_x", "1x", "", "x" * 40):
        assert not mcp_utils.valid_name(bad)


# --- the registry ------------------------------------------------------


def test_discover_lists_tools_and_never_stores(env):
    client, litellm = env
    response = client.post(
        f"{SERVERS}/discover",
        json={"url": URL, "credential": {"value": "ghp_secret"}},
    )
    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "name": "search_issues",
            "description": "Search issues",
            "read_only": True,
        },
        {
            "name": "create_issue",
            "description": "Create an issue",
            "read_only": None,
        },
    ]
    sent = litellm.list_mcp_tools.call_args.args[0]
    assert sent["transport"] == "http"
    assert sent["static_headers"] == {"Authorization": "Bearer ghp_secret"}
    assert ss._memory == {}


def test_discover_failure_is_a_502_with_the_proxys_words(env):
    client, litellm = env
    litellm.list_mcp_tools.side_effect = ll.LiteLLMError(
        "Could not list the tools: unreachable"
    )
    response = client.post(f"{SERVERS}/discover", json={"url": URL})
    assert response.status_code == 502
    assert "unreachable" in response.json()["detail"]


def test_create_stores_the_secret_registers_and_scopes_the_team(env):
    client, litellm = env
    name = _name()
    response = _create(client, name=name, allowed_tools=["search_issues"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["credential_mode"] == "shared"
    assert body["my_credential"] == "not_needed"
    assert body["credential_set_at"] is not None
    assert body["status"] == "connected"
    # Times carry their offset: a naive one is read in the browser's zone.
    from datetime import datetime

    for field in ("checked_at", "credential_set_at"):
        assert datetime.fromisoformat(body[field]).tzinfo is not None
    assert [t["name"] for t in body["tools"]] == [
        "search_issues",
        "create_issue",
    ]
    assert body["tool_prefix"].startswith(name.replace("_", ""))
    assert body["tool_prefix"].endswith("-")
    assert "ghp_secret" not in response.text

    server_id = uuid.UUID(body["id"])
    secret = ss._memory[
        (get_default_namespace(), f"mcp-{id8(server_id)}-credentials")
    ]
    assert secret == {"credential": "ghp_secret"}

    registered = litellm.register_mcp_server.call_args.args[0]
    assert registered["alias"] == registered["server_name"]
    assert registered["alias"].startswith(name.replace("_", ""))
    assert registered["transport"] == "http"
    assert registered["allowed_tools"] == ["search_issues"]
    assert registered["static_headers"] == {
        "Authorization": "Bearer ghp_secret"
    }
    # The team may use what was just registered.
    team_id, team_ids = litellm.set_team_mcp_servers.call_args.args
    assert team_id == "team-1"
    rows = {r["id"]: r for r in client.get(SERVERS).json()}
    assert body["id"] in rows
    assert litellm.register_mcp_server.call_count == 1
    assert len(team_ids) == len(set(team_ids)) >= 1
    assert all(i.startswith("srv-") for i in team_ids)


def test_custom_header_credential(env):
    client, litellm = env
    response = _create(
        client,
        credential={
            "auth_type": "header",
            "auth_header": "X-Api-Key",
            "value": "k3y",
        },
    )
    assert response.status_code == 201, response.text
    registered = litellm.register_mcp_server.call_args.args[0]
    assert registered["static_headers"] == {"X-Api-Key": "k3y"}
    missing = _create(client, credential={"auth_type": "header", "value": "k"})
    assert missing.status_code == 400


def test_create_without_a_credential(env):
    client, litellm = env
    response = _create(client, credential=None)
    assert response.status_code == 201, response.text
    assert response.json()["credential_mode"] == "none"
    assert (
        litellm.register_mcp_server.call_args.args[0]["static_headers"] == {}
    )
    assert ss._memory == {}


def test_duplicate_name_is_a_409_and_bad_input_a_400(env):
    client, _ = env
    name = _name()
    assert _create(client, name=name).status_code == 201
    assert _create(client, name=name).status_code == 409
    assert _create(client, name="Git-Hub").status_code == 400
    assert _create(client, url="http://mcp.example.com/mcp").status_code == 400
    assert _create(client, transport="stdio").status_code == 400


def test_a_failed_registration_leaves_nothing_behind(env):
    client, litellm = env
    litellm.register_mcp_server.side_effect = ll.LiteLLMError("proxy down")
    name = _name()
    response = _create(client, name=name)
    assert response.status_code == 502
    assert ss._memory == {}
    assert name not in [s["name"] for s in client.get(SERVERS).json()]


def test_a_failed_team_update_removes_the_registered_server(env):
    client, litellm = env
    litellm.register_mcp_server.side_effect = None
    litellm.register_mcp_server.return_value = "srv-x"
    litellm.set_team_mcp_servers.side_effect = ll.LiteLLMError("team gone")
    assert _create(client).status_code == 502
    litellm.delete_mcp_server.assert_called_once_with("srv-x")
    assert ss._memory == {}


def test_a_team_created_on_first_use_does_not_keep_a_failed_server(
    env, monkeypatch
):
    """``ensure_org_key`` commits when it creates the team. Found on the
    live stack: with the team made after the row was flushed, that
    commit kept the row of a registration that then failed."""
    client, litellm = env

    def team_with_a_commit(litellm, db, user):
        db.commit()
        return "team-1"

    monkeypatch.setattr("api.mcp._team_id", team_with_a_commit)
    litellm.set_team_mcp_servers.side_effect = ll.LiteLLMError("team gone")
    name = _name()
    assert _create(client, name=name).status_code == 502
    assert name not in [s["name"] for s in client.get(SERVERS).json()]
    assert litellm.set_team_mcp_servers.call_args.args[0] == "team-1"


def test_writes_are_for_admins_and_reads_for_members(env):
    client, _ = env
    created = _create(client).json()
    member = client.post(
        SERVERS, json={"name": _name(), "url": URL}, headers=ALICE
    )
    assert member.status_code == 403
    assert (
        client.post(
            f"{SERVERS}/discover", json={"url": URL}, headers=ALICE
        ).status_code
        == 403
    )
    assert (
        client.delete(f"{SERVERS}/{created['id']}", headers=ALICE).status_code
        == 403
    )
    seen = client.get(SERVERS, headers=ALICE).json()
    mine = next(s for s in seen if s["id"] == created["id"])
    # A member does not learn when the credential was set.
    assert mine["credential_set_at"] is None


def test_another_organization_sees_nothing(env):
    client, _ = env
    created = _create(client).json()
    assert created["id"] not in [
        s["id"] for s in client.get(SERVERS, headers=OUTSIDER).json()
    ]


def test_update_resends_the_server_with_the_stored_credential(env):
    client, litellm = env
    created = _create(client).json()
    response = client.patch(
        f"{SERVERS}/{created['id']}",
        json={"allowed_tools": ["search_issues"], "description": "Issues"},
    )
    assert response.status_code == 200, response.text
    server_id, sent = litellm.update_mcp_server.call_args.args
    assert server_id.startswith("srv-")
    assert sent["allowed_tools"] == ["search_issues"]
    assert sent["static_headers"] == {"Authorization": "Bearer ghp_secret"}

    all_tools = client.patch(
        f"{SERVERS}/{created['id']}", json={"allow_all_tools": True}
    )
    assert all_tools.json()["allowed_tools"] is None


def test_update_replaces_and_removes_the_credential(env):
    client, litellm = env
    created = _create(client).json()
    key = (
        get_default_namespace(),
        f"mcp-{id8(uuid.UUID(created['id']))}-credentials",
    )
    client.patch(
        f"{SERVERS}/{created['id']}", json={"credential": {"value": "new"}}
    )
    assert ss._memory[key] == {"credential": "new"}
    removed = client.patch(
        f"{SERVERS}/{created['id']}", json={"remove_credential": True}
    )
    assert removed.json()["credential_mode"] == "none"
    assert key not in ss._memory
    assert litellm.update_mcp_server.call_args.args[1]["static_headers"] == {}


def test_disabling_takes_the_server_out_of_the_team(env):
    client, litellm = env
    created = _create(client).json()
    before = litellm.set_team_mcp_servers.call_args.args[1]
    client.patch(f"{SERVERS}/{created['id']}", json={"enabled": False})
    after = litellm.set_team_mcp_servers.call_args.args[1]
    assert len(after) == len(before) - 1


def test_refresh_keeps_the_last_tools_when_the_server_is_down(env):
    client, litellm = env
    created = _create(client).json()
    litellm.list_mcp_tools.side_effect = ll.LiteLLMError("unreachable")
    response = client.post(f"{SERVERS}/{created['id']}/refresh")
    assert response.status_code == 200
    assert response.json()["status"] == "unreachable"
    assert len(response.json()["tools"]) == 2


def test_delete_fails_closed_when_the_proxy_refuses(env):
    """The proxy holds a copy of the shared credential; once the row is
    gone nothing would retry, so a refused delete keeps everything."""
    client, litellm = env
    created = _create(client).json()
    litellm.delete_mcp_server.side_effect = ll.LiteLLMError("down")
    response = client.delete(f"{SERVERS}/{created['id']}")
    assert response.status_code == 502
    assert "stays" in response.json()["detail"]
    assert len(ss._memory) == 1
    assert created["id"] in [s["id"] for s in client.get(SERVERS).json()]

    litellm.delete_mcp_server.side_effect = None
    assert client.delete(f"{SERVERS}/{created['id']}").status_code == 204
    assert ss._memory == {}
    assert created["id"] not in [s["id"] for s in client.get(SERVERS).json()]


def test_a_failed_update_leaves_every_credential_as_it_was(env):
    client, litellm = env
    server = _create_per_user(client).json()
    url = f"{SERVERS}/{server['id']}"
    client.put(f"{url}/credential", json={"value": "a"}, headers=ALICE)
    before = dict(ss._memory)
    litellm.update_mcp_server.side_effect = ll.LiteLLMError("proxy down")
    for body in (
        {"credential_mode": "shared", "credential": {"value": "s"}},
        {"credential_mode": "none"},
    ):
        assert client.patch(url, json=body).status_code == 502
        assert ss._memory == before
    listed = {s["id"]: s for s in client.get(SERVERS, headers=ALICE).json()}
    assert listed[server["id"]]["credential_mode"] == "per_user"
    assert listed[server["id"]]["my_credential"] == "set"


def test_a_change_that_deletes_members_credentials_must_be_said(env):
    client, _ = env
    server = _create_per_user(client).json()
    url = f"{SERVERS}/{server['id']}"
    for body in (
        {"credential": {"value": "looks-like-a-rotation"}},
        {"remove_credential": True},
    ):
        refused = client.patch(url, json=body)
        assert refused.status_code == 400
        assert "credential_mode" in refused.json()["detail"]
    assert (
        client.patch(url, json={"credential_mode": "bogus"}).status_code == 400
    )
    other_shape = {
        "credential_mode": "per_user",
        "credential": {
            "auth_type": "header",
            "auth_header": "X-K",
            "value": "v",
        },
    }
    assert client.patch(url, json=other_shape).status_code == 400
    # The admin's own, in the same shape, replaces only theirs.
    same = {"credential_mode": "per_user", "credential": {"value": "admin-2"}}
    assert client.patch(url, json=same).status_code == 200
    assert len(_secret_names()) == 1


def test_help_url_must_be_a_web_address(env):
    client, _ = env
    bad = _create_per_user(client, credential_help_url="javascript:alert(1)")
    assert bad.status_code == 422


def test_without_litellm_writes_and_the_endpoint_answer_503(
    client, monkeypatch
):
    monkeypatch.setattr("api.mcp.litellm_client", lambda: None)
    assert _create(client).status_code == 503
    assert client.post(ENDPOINT, json={}).status_code == 503
    assert client.get(SERVERS).status_code == 200


# --- the endpoint ------------------------------------------------------


def _proxy(handler):
    return ll.LiteLLMClient(
        ll.LiteLLMSettings(url="http://litellm.test", master_key="sk-master"),
        transport=httpx.MockTransport(handler),
    )


RPC = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def test_endpoint_relays_with_the_org_key_and_an_allow_list_of_headers(
    env, monkeypatch
):
    client, _ = env
    name = _create(client).json()["name"]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "mcp-session-id": "sess-1",
                "x-internal": "no",
            },
            content=b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n',
        )

    monkeypatch.setattr("api.mcp.litellm_client", lambda: _proxy(handler))
    response = client.post(
        ENDPOINT,
        json=RPC,
        headers={
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": "sess-0",
            "MCP-Protocol-Version": "2025-06-18",
            "Cookie": "session=1",
            "X-Org": "default",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["mcp-session-id"] == "sess-1"
    assert "x-internal" not in response.headers
    assert '"tools":[]' in response.text

    request = seen["request"]
    assert request.url.path == "/mcp"
    assert json.loads(request.content) == RPC
    assert request.headers["x-litellm-api-key"] == "Bearer sk-org"
    # The client's own bearer never reaches the proxy, which would read
    # it as a LiteLLM key; and the master key does not travel on a
    # member's request either.
    assert request.headers["authorization"] == "Bearer sk-org"
    assert request.headers["mcp-session-id"] == "sess-0"
    assert request.headers["mcp-protocol-version"] == "2025-06-18"
    assert "cookie" not in request.headers
    assert "x-org" not in request.headers
    assert name.replace("_", "") in request.headers["x-mcp-servers"]


def test_endpoint_selects_servers_by_name_and_refuses_an_unknown_one(
    env, monkeypatch
):
    client, _ = env
    first = _create(client).json()["name"]
    second = _create(client).json()["name"]
    seen = {}

    def handler(request):
        seen["servers"] = request.headers["x-mcp-servers"]
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {}}
        )

    monkeypatch.setattr("api.mcp.litellm_client", lambda: _proxy(handler))
    ok = client.post(ENDPOINT, json=RPC, headers={"X-Mcp-Servers": first})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("application/json")
    assert seen["servers"].startswith(first.replace("_", ""))
    assert second.replace("_", "") not in seen["servers"]
    bad = client.post(ENDPOINT, json=RPC, headers={"X-Mcp-Servers": "nope"})
    assert bad.status_code == 400
    assert "nope" in bad.json()["detail"]


def test_endpoint_passes_a_protocol_status_through(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(
        "api.mcp.litellm_client",
        lambda: _proxy(
            lambda request: httpx.Response(404, json={"detail": "gone"})
        ),
    )
    assert client.post(ENDPOINT, json=RPC).status_code == 404
    monkeypatch.setattr(
        "api.mcp.litellm_client",
        lambda: _proxy(lambda request: httpx.Response(202)),
    )
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert client.post(ENDPOINT, json=note).status_code == 202


def test_endpoint_has_no_get_stream(env, monkeypatch):
    """A GET stream would hold a worker thread for as long as an IDE
    stays connected; the protocol allows 405."""
    client, _ = env

    def handler(request):
        raise AssertionError("a GET must not reach the proxy")

    monkeypatch.setattr("api.mcp.litellm_client", lambda: _proxy(handler))
    response = client.get(ENDPOINT)
    assert response.status_code == 405
    assert "POST" in response.headers["allow"]


def test_endpoint_is_502_when_the_proxy_is_unreachable(env, monkeypatch):
    client, _ = env

    def handler(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("api.mcp.litellm_client", lambda: _proxy(handler))
    assert client.post(ENDPOINT, json=RPC).status_code == 502


def test_a_viewer_cannot_use_tools_and_a_member_can(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(
        "api.mcp.litellm_client",
        lambda: _proxy(lambda request: httpx.Response(200, json={})),
    )
    assert client.post(ENDPOINT, json=RPC, headers=VIEWER).status_code == 403
    assert client.post(ENDPOINT, json=RPC, headers=ALICE).status_code == 200


def test_the_endpoint_is_not_audited_but_the_registry_is():
    from audit.events import should_record

    assert not should_record("POST", "/v1alpha1/mcp")
    assert not should_record("DELETE", "/v1alpha1/mcp/")
    assert should_record("POST", "/v1alpha1/mcp/servers")
    assert should_record("DELETE", f"/v1alpha1/mcp/servers/{uuid.uuid4()}")


# --- a member's own credential (per_user) ------------------------------


BOB = {"X-Dev-User": "bob"}


def _create_per_user(client, **overrides):
    body = {
        "credential_mode": "per_user",
        "credential": {"auth_type": "bearer", "value": "admin-token"},
        "credential_help_url": "https://github.com/settings/tokens",
    }
    body.update(overrides)
    return _create(client, **body)


def _secret_names():
    return sorted(name for _, name in ss._memory)


def test_per_user_server_registers_without_a_credential(env):
    client, litellm = env
    body = _create_per_user(client).json()
    assert body["credential_mode"] == "per_user"
    assert body["credential_header"] == "Authorization"
    assert body["credential_help_url"] == "https://github.com/settings/tokens"
    # The admin's own is stored as theirs, and was used for the test...
    assert body["my_credential"] == "set"
    assert litellm.list_mcp_tools.call_args.args[0]["static_headers"] == {
        "Authorization": "Bearer admin-token"
    }
    # ...but the proxy holds none.
    assert (
        litellm.register_mcp_server.call_args.args[0]["static_headers"] == {}
    )
    assert len(_secret_names()) == 1 and "-usr-" in _secret_names()[0]
    # per_user without a credential of the admin's own is refused.
    assert (
        _create(
            client, credential_mode="per_user", credential=None
        ).status_code
        == 400
    )


def test_a_member_connects_their_own_and_it_travels_with_their_calls(
    env, monkeypatch
):
    client, litellm = env
    server = _create_per_user(client).json()
    own = f"{SERVERS}/{server['id']}/credential"
    listed = {s["id"]: s for s in client.get(SERVERS, headers=ALICE).json()}
    assert listed[server["id"]]["my_credential"] == "missing"

    # A value the server refuses is not stored.
    litellm.list_mcp_tools.side_effect = ll.LiteLLMError("HTTP 401")
    refused = client.put(own, json={"value": "bad"}, headers=ALICE)
    assert refused.status_code == 400
    assert "did not accept" in refused.json()["detail"]
    litellm.list_mcp_tools.side_effect = None

    saved = client.put(own, json={"value": "alice-token"}, headers=ALICE)
    assert saved.status_code == 200, saved.text
    assert saved.json()["my_credential"] == "set"
    assert "alice-token" not in saved.text
    assert litellm.list_mcp_tools.call_args.args[0]["static_headers"] == {
        "Authorization": "Bearer alice-token"
    }
    # A viewer cannot use tools, so cannot store a credential either.
    assert (
        client.put(own, json={"value": "v"}, headers=VIEWER).status_code == 403
    )

    seen = []

    def handler(request):
        seen.append(dict(request.headers))
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {}}
        )

    monkeypatch.setattr("api.mcp.litellm_client", lambda: _proxy(handler))
    alias = server["tool_prefix"].rstrip("-")
    header = f"x-mcp-{alias}-authorization"

    assert client.post(ENDPOINT, json=RPC, headers=ALICE).status_code == 200
    assert seen[-1][header] == "Bearer alice-token"
    assert client.post(ENDPOINT, json=RPC).status_code == 200
    assert seen[-1][header] == "Bearer admin-token"

    # Bob has none: the server is left out of "all", and asked for by
    # name it says what to do.
    assert client.post(ENDPOINT, json=RPC, headers=BOB).status_code == 200
    assert header not in seen[-1]
    assert alias not in seen[-1]["x-mcp-servers"]
    named = client.post(
        ENDPOINT,
        json=RPC,
        headers={**BOB, "X-Mcp-Servers": server["name"]},
    )
    assert named.status_code == 409
    assert server["name"] in named.json()["detail"]

    # Disconnect: gone from the store and from the next call.
    before = len(_secret_names())
    assert (
        client.delete(own, headers=ALICE).json()["my_credential"] == "missing"
    )
    assert len(_secret_names()) == before - 1
    client.post(ENDPOINT, json=RPC, headers=ALICE)
    assert header not in seen[-1]


def test_own_credential_is_refused_on_a_shared_server(env):
    client, _ = env
    server = _create(client).json()
    response = client.put(
        f"{SERVERS}/{server['id']}/credential",
        json={"value": "x"},
        headers=ALICE,
    )
    assert response.status_code == 409


def test_switching_modes_leaves_no_credential_behind(env):
    client, litellm = env
    server = _create(client).json()
    url = f"{SERVERS}/{server['id']}"
    switched = client.patch(
        url,
        json={
            "credential_mode": "per_user",
            "credential": {"auth_type": "bearer", "value": "admin-own"},
        },
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["credential_mode"] == "per_user"
    assert litellm.update_mcp_server.call_args.args[1]["static_headers"] == {}
    assert all("-usr-" in n for n in _secret_names())
    client.put(f"{url}/credential", json={"value": "a"}, headers=ALICE)
    assert len(_secret_names()) == 2

    back = client.patch(
        url,
        json={
            "credential_mode": "shared",
            "credential": {"value": "shared-again"},
        },
    )
    assert back.json()["credential_mode"] == "shared"
    assert litellm.update_mcp_server.call_args.args[1]["static_headers"] == {
        "Authorization": "Bearer shared-again"
    }
    assert len(_secret_names()) == 1 and "-usr-" not in _secret_names()[0]
    # per_user needs the admin's own credential in the same request.
    assert (
        client.patch(url, json={"credential_mode": "per_user"}).status_code
        == 400
    )


def test_deleting_the_server_deletes_every_members_secret(env):
    client, _ = env
    server = _create_per_user(client).json()
    client.put(
        f"{SERVERS}/{server['id']}/credential",
        json={"value": "a"},
        headers=ALICE,
    )
    assert len(_secret_names()) == 2
    assert client.delete(f"{SERVERS}/{server['id']}").status_code == 204
    assert ss._memory == {}


def test_remove_member_deletes_their_credentials_last_and_fails_closed(
    env, monkeypatch
):
    from db.database import get_db_direct
    from models.user import User

    client, _ = env
    server = _create_per_user(client).json()
    own = f"{SERVERS}/{server['id']}/credential"
    client.put(own, json={"value": "bob-token"}, headers=BOB)
    db = get_db_direct()
    try:
        bob_id = str(db.query(User).filter(User.sub == "dev:bob").one().id)
    finally:
        db.close()
    member = f"/v1alpha1/organizations/current/members/{bob_id}"
    monkeypatch.setattr("api.organizations.delete_user_key", lambda o, u: None)

    # A LiteLLM step fails: the member stays, with the credential whole.
    def fails(db, org):
        raise ll.LiteLLMError("no rotation")

    monkeypatch.setattr("api.organizations.rotate_org_key", fails)
    before = len(_secret_names())
    assert client.delete(member).status_code == 502
    assert len(_secret_names()) == before
    listed = {s["id"]: s for s in client.get(SERVERS, headers=BOB).json()}
    assert listed[server["id"]]["my_credential"] == "set"

    # The Secret store fails: the member stays too.
    monkeypatch.setattr("api.organizations.rotate_org_key", lambda db, o: None)

    def store_down(db, org_id, user_id):
        raise RuntimeError("secret store down")

    with monkeypatch.context() as m:
        m.setattr(
            "api.organizations.mcp_credentials.delete_for_user", store_down
        )
        refused = client.delete(member)
    assert refused.status_code == 502
    assert "secret store down" not in refused.text

    assert client.delete(member).status_code == 204
    assert len(_secret_names()) == before - 1


# --- mock mode ---------------------------------------------------------


def test_mock_mode_serves_a_registry_and_an_mcp_server(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    tools = client.post(f"{SERVERS}/discover", json={"url": URL}).json()
    assert [t["name"] for t in tools] == ["echo"]
    created = _create(client)
    assert created.status_code == 201, created.text

    def rpc(method, params=None, id=1):
        return client.post(
            ENDPOINT,
            json={
                "jsonrpc": "2.0",
                "id": id,
                "method": method,
                "params": params or {},
            },
        )

    init = rpc("initialize", {"protocolVersion": "2025-03-26"})
    assert init.json()["result"]["protocolVersion"] == "2025-03-26"
    note = client.post(
        ENDPOINT,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert note.status_code == 202
    assert rpc("tools/list").json()["result"]["tools"][0]["name"] == "echo"
    called = rpc(
        "tools/call", {"name": "echo", "arguments": {"message": "hi"}}
    )
    assert called.json()["result"]["content"] == [
        {"type": "text", "text": "hi"}
    ]
    assert client.get(ENDPOINT).status_code == 405
    assert rpc("nope").json()["error"]["code"] == -32601
