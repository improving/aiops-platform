"""OAuth sign-in to an MCP server (utils/mcp_oauth.py, the oauth routes
of api/mcp.py, the refresh in utils/mcp_credentials.py). The
authorization server is an httpx.MockTransport; LiteLLM is a mock; the
secret store is the in-process one."""

import json
import time
import uuid
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from core import create_app
from db.database import get_db_direct
from models.mcp_server import McpOAuthState
from utils import mcp as mcp_utils
from utils import mcp_credentials as creds
from utils import mcp_oauth
from utils import secret_store as ss

SERVERS = "/v1alpha1/mcp/servers"
ENDPOINT = "/v1alpha1/mcp"
CALLBACK = "/v1alpha1/mcp/oauth/callback"
URL = "https://mcp.linear.example/mcp"
ISSUER = "https://auth.linear.example"
UI = "https://ui.platform.example"
ALICE = {"X-Dev-User": "alice"}
BOB = {"X-Dev-User": "bob"}
VIEWER = {"X-Dev-User": "viewer"}
RPC = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


class FakeAuthorizationServer:
    """Metadata, dynamic registration and a token endpoint."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.registered: list[dict] = []
        self.token_forms: list[dict] = []
        self.token_answer = None  # a callable(form) -> httpx.Response
        self.counter = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if (
            url
            == "https://mcp.linear.example/.well-known/oauth-protected-resource/mcp"
        ):
            return httpx.Response(
                200, json={"authorization_servers": [ISSUER]}
            )
        if url == f"{ISSUER}/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "registration_endpoint": f"{ISSUER}/register",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if url == f"{ISSUER}/register":
            self.registered.append(json.loads(request.content))
            return httpx.Response(201, json={"client_id": "client-123"})
        if url == f"{ISSUER}/token":
            form = {
                k: v[0] for k, v in parse_qs(request.content.decode()).items()
            }
            self.token_forms.append(form)
            if self.token_answer is not None:
                return self.token_answer(form)
            self.counter += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"access-{self.counter}",
                    "refresh_token": f"refresh-{self.counter}",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("AIOPS_SECRET_STORE", "memory")
    monkeypatch.setenv("AIOPS_UI_URL", UI)
    monkeypatch.setattr(mcp_utils, "_resolve", lambda host: ["93.184.216.34"])
    ss._memory.clear()
    creds._value_cache.clear()
    # No real waits for another replica's write.
    monkeypatch.setattr(creds, "RACE_WAITS_SECONDS", (0.0,))
    yield
    ss._memory.clear()
    creds._value_cache.clear()


@pytest.fixture
def authz(monkeypatch):
    server = FakeAuthorizationServer()
    monkeypatch.setattr(
        mcp_oauth,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(server.handler)),
    )
    return server


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def env(client, monkeypatch, authz):
    litellm = mock.Mock()
    litellm.list_mcp_tools.return_value = [{"name": "list_issues"}]
    litellm.register_mcp_server.side_effect = lambda body: (
        f"srv-{uuid.uuid4().hex[:6]}"
    )
    monkeypatch.setattr("api.mcp.litellm_client", lambda: litellm)
    monkeypatch.setattr("api.mcp.org_key", lambda db, user: "sk-org")
    monkeypatch.setattr("api.mcp._team_id", lambda litellm, db, user: "team-1")
    return client, litellm, authz


def _create(client, **overrides):
    body = {
        "name": f"linear_{uuid.uuid4().hex[:6]}",
        "url": URL,
        "oauth": {},
    }
    body.update(overrides)
    return client.post(SERVERS, json=body)


def _sign_in(client, server_id, headers=None):
    """Start, then post back what the authorization server would send."""
    started = client.post(
        f"{SERVERS}/{server_id}/oauth/start", headers=headers
    )
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
    done = client.post(
        CALLBACK,
        json={"code": "the-code", "state": query["state"][0]},
        headers=headers,
    )
    return query, done


# --- the protocol ------------------------------------------------------


def test_discovery_follows_the_resource_to_its_authorization_server(authz):
    metadata = mcp_oauth.discover(URL)
    assert metadata["issuer"] == ISSUER
    assert metadata["token_endpoint"] == f"{ISSUER}/token"
    client_id, secret = mcp_oauth.register_client(metadata)
    assert (client_id, secret) == ("client-123", None)
    sent = authz.registered[0]
    assert sent["redirect_uris"] == [f"{UI}/mcp-servers/oauth/callback"]
    assert sent["token_endpoint_auth_method"] == "none"


def test_discovery_refuses_another_issuer_and_a_private_endpoint(monkeypatch):
    def lying(request):
        if "oauth-authorization-server" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://evil.example",
                    "authorization_endpoint": "https://evil.example/a",
                    "token_endpoint": "https://evil.example/t",
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        mcp_oauth,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lying)),
    )
    with pytest.raises(mcp_oauth.OAuthError, match="another issuer"):
        mcp_oauth.discover(URL)

    def private(request):
        if "oauth-authorization-server" in str(request.url):
            origin = "https://mcp.linear.example"
            return httpx.Response(
                200,
                json={
                    "issuer": origin,
                    "authorization_endpoint": f"{origin}/a",
                    "token_endpoint": "https://10.0.0.5/token",
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        mcp_oauth,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(private)),
    )
    with pytest.raises(mcp_oauth.OAuthError, match="public address"):
        mcp_oauth.discover(URL)


def _metadata_server(monkeypatch, metadata):
    def handler(request):
        if "oauth-authorization-server" in str(request.url):
            return httpx.Response(200, json=metadata)
        return httpx.Response(404)

    monkeypatch.setattr(
        mcp_oauth,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_the_endpoints_belong_to_the_issuer_or_to_hosts_the_admin_named(
    monkeypatch,
):
    """The mix-up: the consent page of an honest authorization server,
    and a token endpoint of somebody else that gets the code with its
    verifier."""
    origin = "https://mcp.linear.example"
    _metadata_server(
        monkeypatch,
        {
            "issuer": origin,
            "authorization_endpoint": "https://honest.example/authorize",
            "token_endpoint": f"{origin}/token",
        },
    )
    with pytest.raises(mcp_oauth.OAuthError, match="honest.example"):
        mcp_oauth.discover(URL)
    _metadata_server(
        monkeypatch,
        {
            "issuer": origin,
            "authorization_endpoint": f"{origin}/authorize",
            "token_endpoint": "https://tokens.example/token",
            "authorization_response_iss_parameter_supported": True,
        },
    )
    with pytest.raises(mcp_oauth.OAuthError, match="oauth.allow_hosts"):
        mcp_oauth.discover(URL)
    found = mcp_oauth.discover(URL, allow_hosts=["tokens.example"])
    assert found["token_endpoint"] == "https://tokens.example/token"
    assert found["iss_required"] is True


def test_an_answer_names_the_issuer_the_sign_in_went_to():
    oauth = {"issuer": ISSUER, "iss_required": True}
    mcp_oauth.check_issuer(oauth, ISSUER + "/")
    with pytest.raises(mcp_oauth.OAuthError, match="another"):
        mcp_oauth.check_issuer(oauth, "https://evil.example")
    with pytest.raises(mcp_oauth.OAuthError, match="does not say"):
        mcp_oauth.check_issuer(oauth, None)
    # A server that never promised the parameter may leave it out, but
    # a wrong one is still refused.
    mcp_oauth.check_issuer({"issuer": ISSUER}, None)
    with pytest.raises(mcp_oauth.OAuthError):
        mcp_oauth.check_issuer({"issuer": ISSUER}, "https://evil.example")


def test_an_answer_that_is_too_large_or_no_object_is_no_answer(monkeypatch):
    origin = "https://mcp.linear.example"
    answers = {
        "large": httpx.Response(200, content=b" " * (mcp_oauth.MAX_BODY + 1)),
        "list": httpx.Response(200, json=["not", "an", "object"]),
        "text": httpx.Response(200, content=b"<html>"),
    }
    for answer in answers.values():
        monkeypatch.setattr(
            mcp_oauth,
            "http_client",
            lambda answer=answer: httpx.Client(
                transport=httpx.MockTransport(lambda request: answer)
            ),
        )
        with pytest.raises(mcp_oauth.OAuthError, match="no OAuth metadata"):
            mcp_oauth.discover(URL)
        # The same answers from a registration and a token endpoint are a
        # refusal with a reason, never a 500.
        with pytest.raises(mcp_oauth.OAuthError):
            mcp_oauth.register_client(
                {"registration_endpoint": f"{origin}/register"}
            )
        with pytest.raises(mcp_oauth.OAuthError):
            mcp_oauth.exchange_code(
                {"client_id": "c", "token_endpoint": f"{origin}/token"},
                None,
                URL,
                "code",
                "verifier",
            )


def test_a_token_lifetime_is_a_sane_number(monkeypatch):
    origin = "https://mcp.linear.example"
    for given, expected in ((10**400, mcp_oauth.MAX_EXPIRES_IN), (-5, 0)):
        monkeypatch.setattr(
            mcp_oauth,
            "http_client",
            lambda given=given: httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        content=json.dumps(
                            {"access_token": "a", "expires_in": given}
                        ),
                    )
                )
            ),
        )
        tokens = mcp_oauth.exchange_code(
            {"client_id": "c", "token_endpoint": f"{origin}/token"},
            None,
            URL,
            "code",
            "verifier",
        )
        assert abs(tokens.expires_at - time.time() - expected) < 5


def test_no_metadata_and_no_ui_url_say_why(monkeypatch):
    monkeypatch.setattr(
        mcp_oauth,
        "http_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        ),
    )
    with pytest.raises(mcp_oauth.OAuthError, match="no OAuth metadata"):
        mcp_oauth.discover(URL)
    monkeypatch.delenv("AIOPS_UI_URL")
    with pytest.raises(mcp_oauth.OAuthError, match="AIOPS_UI_URL"):
        mcp_oauth.redirect_uri()


def test_the_authorization_url_carries_pkce_state_and_the_resource():
    oauth = {
        "authorization_endpoint": f"{ISSUER}/authorize",
        "client_id": "client-123",
        "scopes": ["read", "write"],
    }
    verifier = mcp_oauth.new_verifier()
    url = mcp_oauth.authorization_url(oauth, URL, "the-state", verifier)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query["response_type"] == "code"
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == mcp_oauth.challenge(verifier)
    assert verifier not in url
    assert query["resource"] == URL
    assert query["scope"] == "read write"
    assert query["redirect_uri"] == f"{UI}/mcp-servers/oauth/callback"


# --- the routes --------------------------------------------------------


def test_a_sign_in_server_is_registered_without_a_credential_or_tools(env):
    client, litellm, authz = env
    created = _create(client)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["oauth"] is True
    assert body["credential_mode"] == "per_user"
    assert body["my_credential"] == "missing"
    assert body["tools"] == []
    assert (
        litellm.register_mcp_server.call_args.args[0]["static_headers"] == {}
    )
    litellm.list_mcp_tools.assert_not_called()
    assert authz.registered, "the platform registered itself as a client"
    # Nothing secret in the answer, and no pasted value for such a server.
    assert "client-123" not in created.text
    pasted = client.put(
        f"{SERVERS}/{body['id']}/credential",
        json={"value": "x"},
        headers=ALICE,
    )
    assert pasted.status_code == 409
    # The client and every member's tokens belong to this URL and this
    # kind of sign-in: neither changes on a PATCH.
    for change in (
        {"credential_mode": "none"},
        {"remove_credential": True},
        {"credential": {"auth_type": "bearer", "value": "x"}},
        {"url": "https://other.example.com/mcp"},
    ):
        refused = client.patch(f"{SERVERS}/{body['id']}", json=change)
        assert refused.status_code == 409, (change, refused.text)
    kept = client.patch(
        f"{SERVERS}/{body['id']}", json={"description": "still here"}
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["oauth"] is True
    # A check by somebody who has not signed in is no check: it must not
    # mark the server unreachable for the members who have.
    unchecked = client.post(f"{SERVERS}/{body['id']}/refresh")
    assert unchecked.status_code == 409
    assert "Sign in" in unchecked.json()["detail"]


def test_a_client_the_admin_made_is_used_and_its_secret_kept_apart(env):
    client, _, authz = env
    created = _create(
        client, oauth={"client_id": "gh-app", "client_secret": "s3cret"}
    )
    assert created.status_code == 201, created.text
    assert not authz.registered
    assert "s3cret" not in created.text
    names = [name for _, name in ss._memory]
    assert any(n.endswith("-oauth-client") for n in names)
    assert (
        client.delete(f"{SERVERS}/{created.json()['id']}").status_code == 204
    )
    assert ss._memory == {}


def test_a_member_signs_in_and_their_token_travels_with_their_calls(
    env, monkeypatch
):
    client, litellm, authz = env
    server = _create(client).json()
    query, done = _sign_in(client, server["id"], ALICE)
    assert done.status_code == 200, done.text
    assert done.json()["my_credential"] == "set"
    # The first member in lists the tools, with their fresh token.
    assert [t["name"] for t in done.json()["tools"]] == ["list_issues"]
    sent = litellm.list_mcp_tools.call_args.args[0]
    assert sent["static_headers"] == {"Authorization": "Bearer access-1"}
    assert "access-1" not in done.text

    form = authz.token_forms[0]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code"
    assert form["client_id"] == "client-123"
    assert form["resource"] == URL
    # The verifier that matches the challenge the browser carried.
    assert (
        mcp_oauth.challenge(form["code_verifier"])
        == query["code_challenge"][0]
    )

    seen = []

    def handler(request):
        seen.append(dict(request.headers))
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {}}
        )

    from utils import litellm as ll

    monkeypatch.setattr(
        "api.mcp.litellm_client",
        lambda: ll.LiteLLMClient(
            ll.LiteLLMSettings(url="http://litellm.test", master_key="sk-m"),
            transport=httpx.MockTransport(handler),
        ),
    )
    header = f"x-mcp-{server['tool_prefix'].rstrip('-')}-authorization"
    assert client.post(ENDPOINT, json=RPC, headers=ALICE).status_code == 200
    assert seen[-1][header] == "Bearer access-1"
    # Bob has not signed in: the server is left out for him.
    assert client.post(ENDPOINT, json=RPC, headers=BOB).status_code == 200
    assert header not in seen[-1]


def test_a_state_is_the_members_own_single_use_and_short_lived(env):
    client, _, _ = env
    server = _create(client).json()
    start = f"{SERVERS}/{server['id']}/oauth/start"

    state = parse_qs(
        urlsplit(
            client.post(start, headers=ALICE).json()["authorization_url"]
        ).query
    )["state"][0]
    # Somebody else posts it: refused, and still good for its owner.
    stolen = client.post(
        CALLBACK, json={"code": "c", "state": state}, headers=BOB
    )
    assert stolen.status_code == 400
    assert (
        client.post(
            CALLBACK, json={"code": "c", "state": state}, headers=ALICE
        ).status_code
        == 200
    )
    # Used once: gone.
    again = client.post(
        CALLBACK, json={"code": "c", "state": state}, headers=ALICE
    )
    assert again.status_code == 400
    assert again.json()["detail"] == stolen.json()["detail"]

    # Older than ten minutes.
    state = parse_qs(
        urlsplit(
            client.post(start, headers=ALICE).json()["authorization_url"]
        ).query
    )["state"][0]
    db = get_db_direct()
    try:
        row = db.get(McpOAuthState, mcp_oauth.hash_state(state))
        assert row.code_verifier and state not in (row.state_hash,)
        row.created_at = datetime.now() - timedelta(minutes=11)
        db.commit()
    finally:
        db.close()
    late = client.post(
        CALLBACK, json={"code": "c", "state": state}, headers=ALICE
    )
    assert late.status_code == 400
    assert (
        client.post(
            CALLBACK, json={"code": "c", "state": "made-up"}
        ).status_code
        == 400
    )
    assert client.post(start, headers=VIEWER).status_code == 403


def test_a_refused_code_is_a_400_with_the_servers_word(env):
    client, _, authz = env
    server = _create(client).json()
    authz.token_answer = lambda form: httpx.Response(
        400, json={"error": "invalid_grant"}
    )
    _, done = _sign_in(client, server["id"], ALICE)
    assert done.status_code == 400
    assert "invalid_grant" in done.json()["detail"]
    listed = {s["id"]: s for s in client.get(SERVERS, headers=ALICE).json()}
    assert listed[server["id"]]["my_credential"] == "missing"


def test_an_answer_of_another_issuer_never_reaches_the_token_endpoint(env):
    client, _, authz = env
    server = _create(client).json()
    assert server["sign_in_host"] == "auth.linear.example"
    started = client.post(f"{SERVERS}/{server['id']}/oauth/start")
    query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
    done = client.post(
        CALLBACK,
        json={
            "code": "the-code",
            "state": query["state"][0],
            "iss": "https://evil.example",
        },
    )
    assert done.status_code == 400
    assert "another authorization server" in done.json()["detail"]
    assert authz.token_forms == []


# --- refresh -----------------------------------------------------------


def _signed_in(env):
    client, _, authz = env
    server = _create(client).json()
    _, done = _sign_in(client, server["id"], ALICE)
    assert done.status_code == 200, done.text
    db = get_db_direct()
    from models.mcp_server import McpServer

    row = db.get(McpServer, uuid.UUID(server["id"]))
    credential = next(c for c in row.credentials if c.user_id is not None)
    return db, row, credential, authz


def _expire(credential, *, refresh_token=None):
    key = next(k for k in ss._memory if k[1] == credential.secret_name)
    ss._memory[key][creds.EXPIRES_KEY] = str(time.time() + 5)
    if refresh_token:
        ss._memory[key][creds.REFRESH_KEY] = refresh_token
    creds._value_cache.clear()
    return key


def test_a_token_near_its_end_is_refreshed_and_the_new_pair_stored(env):
    db, server, credential, authz = _signed_in(env)
    try:
        assert creds.oauth_access_token(db, server, credential) == "access-1"
        assert len(authz.token_forms) == 1  # still fresh: no refresh
        key = _expire(credential)
        assert creds.oauth_access_token(db, server, credential) == "access-2"
        form = authz.token_forms[-1]
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "refresh-1"
        assert ss._memory[key][creds.REFRESH_KEY] == "refresh-2"
        # Served from the cache now, and never beyond the token's life.
        assert creds.oauth_access_token(db, server, credential) == "access-2"
        assert len(authz.token_forms) == 2
        deadline, _ = creds._value_cache[credential.secret_name]
        assert deadline - time.monotonic() <= creds.VALUE_CACHE_SECONDS
    finally:
        db.close()


def test_another_replica_won_the_refresh(env):
    """Rotation: our refresh token was used by another replica, which
    wrote the new pair. Read again, and use what is there."""
    db, server, credential, authz = _signed_in(env)
    try:
        key = _expire(credential)

        def refused(form):
            ss._memory[key].update(
                {
                    creds.SECRET_KEY: "access-from-the-other-replica",
                    creds.REFRESH_KEY: "refresh-rotated",
                    creds.EXPIRES_KEY: str(time.time() + 3600),
                }
            )
            return httpx.Response(400, json={"error": "invalid_grant"})

        authz.token_answer = refused
        assert (
            creds.oauth_access_token(db, server, credential)
            == "access-from-the-other-replica"
        )
        assert credential in server.credentials
    finally:
        db.close()


def test_a_refused_refresh_ends_the_sign_in_and_a_network_error_does_not(env):
    db, server, credential, authz = _signed_in(env)
    try:
        key = _expire(credential)

        def down(form):
            raise httpx.ConnectError("no route")

        authz.token_answer = down
        # Transient: the old token while it still works, nothing deleted.
        assert creds.oauth_access_token(db, server, credential) == "access-1"
        assert key in ss._memory
        # ... and the old token is used for a moment with no new try.
        tries = len(authz.token_forms)
        assert creds.oauth_access_token(db, server, credential) == "access-1"
        assert len(authz.token_forms) == tries
        creds._value_cache.clear()

        authz.token_answer = lambda form: httpx.Response(
            400, json={"error": "invalid_grant"}
        )
        assert creds.oauth_access_token(db, server, credential) is None
        assert key not in ss._memory
        assert credential not in server.credentials
    finally:
        db.close()


def test_mock_mode_runs_the_whole_flow_without_an_authorization_server(
    client, monkeypatch
):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    created = _create(client)
    assert created.status_code == 201, created.text
    started = client.post(f"{SERVERS}/{created.json()['id']}/oauth/start")
    url = urlsplit(started.json()["authorization_url"])
    # Straight back to the UI's callback page.
    assert f"{url.scheme}://{url.netloc}{url.path}" == (
        f"{UI}/mcp-servers/oauth/callback"
    )
    query = parse_qs(url.query)
    done = client.post(
        CALLBACK, json={"code": query["code"][0], "state": query["state"][0]}
    )
    assert done.status_code == 200, done.text
    assert done.json()["my_credential"] == "set"
    assert [t["name"] for t in done.json()["tools"]] == ["echo"]
