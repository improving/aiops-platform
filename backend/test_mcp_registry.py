"""The MCP registry importer: every parser rule against entries
recorded from the real registry (``test_fixtures/mcp_registry.json``),
and the client against a mock transport. No test touches the network."""

import json

import httpx
import pytest

from paths import BACKEND_DIR
from registry import mcp_registry
from registry.entry import SourceError
from utils.mcp import valid_name

FIXTURE = json.loads(
    (BACKEND_DIR / "test_fixtures" / "mcp_registry.json").read_text()
)
BY_RULE = {
    item["_meta"]["fixture"]: mcp_registry.parse_server(item)
    for item in FIXTURE["servers"]
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv(mcp_registry.REGISTRY_URL_ENV, raising=False)
    mcp_registry._cache.clear()
    yield
    mcp_registry._cache.clear()


def test_a_remote_entry_fills_the_add_dialog():
    plain = BY_RULE["remote_plain"]
    assert plain.remote == mcp_registry.RemoteForm(
        "https://api.inference.sh/mcp", "http", "none"
    )
    assert plain.publisher == "ac.inference.sh"
    assert plain.deployable is None and plain.deployable_reason is None
    assert BY_RULE["remote_bearer"].remote.auth_type == "bearer"
    header = BY_RULE["remote_header"].remote
    assert (header.auth_type, header.auth_header) == ("header", "X-API-Key")
    assert BY_RULE["remote_sse_only"].remote.transport == "sse"
    # Several remotes: the first streamable HTTP one.
    assert BY_RULE["remote_several"].remote.url == "https://afmr.ai/mcp"


def test_a_remote_entry_that_cannot_fill_the_dialog_says_why():
    placeholders = BY_RULE["remote_placeholders"]
    assert placeholders.remote is None
    assert "values of yours" in placeholders.remote_reason
    two = BY_RULE["remote_two_secrets"]
    assert two.remote is None and "more than one" in two.remote_reason


def test_an_image_with_streamable_http_becomes_a_catalog_draft():
    entry = BY_RULE["ai.haymon/database"]
    form = entry.deployable
    assert (form.image, form.tag) == ("ghcr.io/haymon-ai/database", "0.7.0")
    # The port and the path come from the URL's placeholders, and a
    # copied loopback bind address would give a pod nobody reaches.
    assert (form.port, form.path) == (9001, "/mcp")
    assert form.args[:5] == ["http", "--host", "0.0.0.0", "--port", "9001"]
    assert any("--host set to 0.0.0.0" in note for note in form.notes)
    host = next(s for s in form.settings if s["name"] == "HTTP_HOST")
    assert host["default"] == "0.0.0.0"

    literal = BY_RULE["ai.midplane/midplane"].deployable
    assert (literal.port, literal.path) == (8080, "/mcp")
    secret = next(s for s in literal.settings if s["name"] == "DATABASE_URL")
    assert secret["secret"] is True and secret["required"] is True
    assert secret["default"] is None


def test_what_the_chart_cannot_run_is_refused_at_import():
    hapi = BY_RULE["ai.com.mcp/hapi-mcp"]
    assert hapi.deployable is None
    assert "docker run options" in hapi.deployable_reason
    stdio = BY_RULE["stdio_only"]
    assert stdio.deployable is None and "stdio" in stdio.deployable_reason
    assert stdio.remote is None and stdio.remote_reason is None


def _image_entry(**package):
    base = {
        "registryType": "oci",
        "identifier": "ghcr.io/acme/server:1.2.3",
        "transport": {"type": "streamable-http", "url": "http://x:8000/mcp"},
    }
    base.update(package)
    return {"server": {"name": "io.acme/server", "packages": [base]}}


@pytest.mark.parametrize(
    "identifier",
    [
        "ghcr.io/acme/server:latest",
        "ghcr.io/acme/server",
        "acme/server:1.0",
        "localhost:5000/acme/server",
    ],
)
def test_an_image_needs_a_registry_host_and_a_pinned_version(identifier):
    entry = mcp_registry.parse_server(_image_entry(identifier=identifier))
    assert entry.deployable is None
    assert "pinned version" in entry.deployable_reason


def test_a_digest_is_a_pinned_version_and_a_secret_default_is_dropped():
    digest = "sha256:" + "a" * 64
    entry = mcp_registry.parse_server(
        _image_entry(
            identifier=f"ghcr.io/acme/server@{digest}",
            environmentVariables=[
                {"name": "TOKEN", "isSecret": True, "default": "hunter2"},
                {"name": "not a name", "default": "x"},
            ],
        )
    )
    form = entry.deployable
    assert form.tag == f"@{digest}"
    assert form.settings == [
        {
            "name": "TOKEN",
            "label": "TOKEN",
            "help": "",
            "secret": True,
            "required": False,
            "default": None,
        }
    ]
    assert any("not a name" in note for note in form.notes)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://{--port-of-nobody}/mcp", "needs a value"),
        ("http://x/mcp", "no port"),
        ("http://x:8000/mcp?token=1", "path"),
        ("http://x:8000/m cp", "path"),
    ],
)
def test_an_endpoint_that_cannot_be_derived_is_a_reason(url, reason):
    entry = mcp_registry.parse_server(
        _image_entry(transport={"type": "streamable-http", "url": url})
    )
    assert entry.deployable is None
    assert reason in entry.deployable_reason


def test_a_transport_header_is_not_deployable_yet():
    entry = mcp_registry.parse_server(
        _image_entry(
            transport={
                "type": "streamable-http",
                "url": "http://x:8000/mcp",
                "headers": [{"name": "Authorization", "isSecret": True}],
            }
        )
    )
    assert "header of its own" in entry.deployable_reason


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("io.github.grafana/mcp-grafana", "mcp_grafana"),
        ("app.linear/linear", "linear"),
        ("ai.autorfp/mcp", "mcp"),
        ("io.x/3d-tools", "s3d_tools"),
        ("io.x/" + "a-very-long-name-" * 4, None),
        ("io.x/---", "s"),
    ],
)
def test_a_catalog_slug_is_always_a_valid_name(name, slug):
    made = mcp_registry.catalog_slug(name)
    assert valid_name(made), made
    assert len(made) <= 32 and not made.endswith("_")
    if slug is not None:
        assert made == slug


def test_every_recorded_name_gives_a_valid_slug():
    for item in FIXTURE["servers"]:
        assert valid_name(mcp_registry.catalog_slug(item["server"]["name"]))


# --- the client --------------------------------------------------------


def _serve(monkeypatch, handler):
    seen: list[httpx.Request] = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        mcp_registry,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(wrapped)),
    )
    return seen


def test_search_asks_for_the_latest_versions_and_is_cached(monkeypatch):
    seen = _serve(
        monkeypatch, lambda request: httpx.Response(200, json=FIXTURE)
    )
    found = mcp_registry.search("grafana", 5)
    assert len(found) == len(FIXTURE["servers"])
    assert dict(seen[0].url.params) == {
        "search": "grafana",
        "limit": "5",
        "version": "latest",
    }
    mcp_registry.search("grafana", 5)
    assert len(seen) == 1
    mcp_registry.search("grafana", 6)
    assert len(seen) == 2


def test_fetch_encodes_the_name(monkeypatch):
    seen = _serve(
        monkeypatch,
        lambda request: httpx.Response(200, json=FIXTURE["servers"][0]),
    )
    entry = mcp_registry.fetch("ac.inference.sh/mcp")
    assert entry.name == "ac.inference.sh/mcp"
    assert seen[0].url.raw_path.endswith(
        b"/v0/servers/ac.inference.sh%2Fmcp/versions/latest"
    )


@pytest.mark.parametrize(
    ("answer", "status", "text"),
    [
        (httpx.Response(429, headers={"retry-after": "30"}), 429, "after 30"),
        (httpx.Response(404), 404, "no such entry"),
        (httpx.Response(500), 502, "answered 500"),
        (httpx.Response(200, content=b"<html>"), 502, "no JSON"),
        (httpx.Response(200, json=[1]), 502, "no JSON object"),
        (
            httpx.Response(200, content=b" " * (mcp_registry.MAX_BODY + 1)),
            502,
            "too large",
        ),
    ],
)
def test_a_refusal_or_a_bad_answer_is_a_source_error(
    monkeypatch, answer, status, text
):
    _serve(monkeypatch, lambda request: answer)
    with pytest.raises(SourceError) as raised:
        mcp_registry.search("x")
    assert raised.value.status == status
    assert text in raised.value.detail


def test_an_outage_is_a_502_and_import_can_be_turned_off(monkeypatch):
    def down(request):
        raise httpx.ConnectError("no route")

    _serve(monkeypatch, down)
    with pytest.raises(SourceError) as raised:
        mcp_registry.search("x")
    assert raised.value.status == 502

    monkeypatch.setenv(mcp_registry.REGISTRY_URL_ENV, "")
    assert mcp_registry.registry_url() is None
    with pytest.raises(SourceError) as off:
        mcp_registry.search("x")
    assert off.value.status == 404
    monkeypatch.setenv(mcp_registry.REGISTRY_URL_ENV, "https://mirror.test/")
    assert mcp_registry.registry_url() == "https://mirror.test"


# --- the routes --------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from core import create_app  # noqa: E402
from utils import mcp as mcp_utils  # noqa: E402
from utils import mcp_oauth  # noqa: E402

SEARCH = "/v1alpha1/mcp/registry/search"
PROBE = "/v1alpha1/mcp/servers/oauth-probe"
ALICE = {"X-Dev-User": "alice"}
VIEWER = {"X-Dev-User": "viewer"}


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_search_answers_previews_for_every_writer(client, monkeypatch):
    _serve(monkeypatch, lambda request: httpx.Response(200, json=FIXTURE))
    found = client.get(SEARCH, params={"q": "x"}, headers=ALICE)
    assert found.status_code == 200, found.text
    by_name = {e["name"]: e for e in found.json()}
    plain = by_name["ac.inference.sh/mcp"]
    assert plain["remote"] == {
        "url": "https://api.inference.sh/mcp",
        "transport": "http",
        "auth_type": "none",
        "auth_header": None,
    }
    assert plain["suggested_name"] == "mcp"
    assert plain["already_added"] is False
    image = by_name["ai.haymon/database"]
    assert image["deployable"] is True and image["remote"] is None
    assert "docker run" in by_name["ai.com.mcp/hapi-mcp"]["deployable_reason"]
    # The raw entry never leaves the backend.
    assert "packages" not in found.text

    assert client.get(SEARCH, headers=VIEWER).status_code == 403
    assert client.get(SEARCH, params={"limit": 51}).status_code == 422
    assert client.get(SEARCH, params={"q": "x" * 101}).status_code == 422


def test_search_passes_a_refusal_on_and_can_be_off(client, monkeypatch):
    _serve(
        monkeypatch,
        lambda request: httpx.Response(429, headers={"retry-after": "9"}),
    )
    limited = client.get(SEARCH, params={"q": "y"})
    assert limited.status_code == 429
    assert "after 9" in limited.json()["detail"]
    monkeypatch.setenv(mcp_registry.REGISTRY_URL_ENV, "")
    off = client.get(SEARCH)
    assert off.status_code == 404
    assert off.json()["detail"] == "Import is turned off"


def test_the_probe_says_yes_no_and_never_fails(client, monkeypatch):
    monkeypatch.setattr(mcp_utils, "_resolve", lambda host: ["93.184.216.34"])
    origin = "https://mcp.example.com"

    def offers(request):
        if "oauth-authorization-server" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "issuer": origin,
                    "authorization_endpoint": f"{origin}/authorize",
                },
            )
        return httpx.Response(404)

    real = httpx.Client
    monkeypatch.setattr(
        mcp_oauth.httpx,
        "Client",
        lambda **kwargs: real(transport=httpx.MockTransport(offers)),
    )
    url = f"{origin}/mcp"
    assert client.post(PROBE, json={"url": url}).json() == {"oauth": True}

    def down(request):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(
        mcp_oauth.httpx,
        "Client",
        lambda **kwargs: real(transport=httpx.MockTransport(down)),
    )
    assert client.post(PROBE, json={"url": url}).json() == {"oauth": False}
    # The URL rule comes first, and its refusal is also only a "no".
    private = client.post(PROBE, json={"url": "http://10.0.0.5/mcp"})
    assert private.json() == {"oauth": False}
    assert (
        client.post(PROBE, json={"url": url}, headers=VIEWER).status_code
        == 403
    )


def test_mock_mode_searches_the_recorded_entries(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    found = client.get(SEARCH, params={"q": "inference"}).json()
    assert [e["name"] for e in found] == ["ac.inference.sh/mcp"]
    assert client.post(
        PROBE, json={"url": "https://oauth.example/mcp"}
    ).json() == {"oauth": True}


# --- hostile entries (anybody can publish to the registry) -------------


@pytest.mark.parametrize(
    "server",
    [
        {"name": "io.x/a", "remotes": 5},
        {
            "name": "io.x/a",
            "remotes": [
                {
                    "type": "streamable-http",
                    "url": "https://x/mcp",
                    "headers": 5,
                }
            ],
        },
        {"name": "io.x/a", "repository": "x"},
        {
            "name": "io.x/a",
            "packages": [{"registryType": "oci", "transport": "x"}],
        },
        {
            "name": "io.x/a",
            "packages": [
                {
                    "registryType": "oci",
                    "identifier": "ghcr.io/a/b:1",
                    "transport": {
                        "type": "streamable-http",
                        "url": "http://[::1:80/mcp",
                    },
                }
            ],
        },
        {"name": 7},
        "not an object",
    ],
)
def test_a_malformed_entry_is_one_entry_left_out(monkeypatch, server):
    """It must never be a 500 for everybody who searches that word."""
    good = FIXTURE["servers"][0]
    _serve(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"servers": [{"server": server}, good, "junk"]}
        ),
    )
    found = mcp_registry.search("anything")
    assert good["server"]["name"] in [e.name for e in found]
    assert all(e.raw == {} for e in found)  # a preview keeps no raw entry


def test_what_becomes_a_link_or_a_text_is_checked():
    entry = mcp_registry.parse_server(
        {
            "server": {
                "name": "io.x/a",
                "description": ["not", "text"],
                "websiteUrl": "javascript:alert(1)",
                "version": 3,
            }
        }
    )
    assert entry.description is None and entry.website is None
    assert entry.version is None


def test_a_fetch_of_a_malformed_entry_is_a_502(monkeypatch):
    _serve(
        monkeypatch,
        lambda request: httpx.Response(200, json={"server": {"name": 5}}),
    )
    with pytest.raises(SourceError) as raised:
        mcp_registry.fetch("io.x/a")
    assert raised.value.status == 502


def test_the_cache_is_bounded(monkeypatch):
    _serve(monkeypatch, lambda request: httpx.Response(200, json=FIXTURE))
    monkeypatch.setattr(mcp_registry, "CACHE_MAX_KEYS", 3)
    for i in range(10):
        mcp_registry.search(f"query {i}")
    assert len(mcp_registry._cache) <= 3


def test_a_variable_that_changes_how_programs_load_is_no_setting():
    entry = mcp_registry.parse_server(
        _image_entry(
            environmentVariables=[
                {"name": "LD_PRELOAD", "default": "/tmp/x.so"},
                {"name": "NODE_OPTIONS"},
                {"name": "API_URL"},
            ]
        )
    )
    assert [s["name"] for s in entry.deployable.settings] == ["API_URL"]
    assert len(entry.deployable.notes) == 2
