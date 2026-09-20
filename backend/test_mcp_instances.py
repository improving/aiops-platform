"""MCP servers the platform deploys: the deploy routes with a fake Helm
controller and a mocked proxy, the poller with pods from the test, and
the hooks in the registry and in the endpoint's selection."""

import uuid
from datetime import datetime, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import mcp_instances as deployed
from core import create_app
from db.database import get_db_direct
from models.mcp_instance import McpInstance
from models.mcp_server import McpServer
from utils import secret_store as ss
from utils.kubernetes_utils import LaunchProgress, PodStatus
from utils.litellm import LiteLLMError

SERVERS = "/v1alpha1/mcp/servers"
INSTANCES = "/v1alpha1/mcp/instances"
CATALOG = "/v1alpha1/mcp/catalog"
ENDPOINT = "/v1alpha1/mcp"
ORGADMIN = {"X-Dev-User": "orgadmin"}
ALICE = {"X-Dev-User": "alice"}
OUTSIDER = {"X-Dev-User": "outsider"}
RPC = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
TOOLS = [{"name": "search_dashboards", "description": "Search"}]
READY = PodStatus(True, "Running")
STARTING = PodStatus(
    False,
    "Pending",
    None,
    LaunchProgress("Pulling image", "Pulling the image", None),
)
CRASHED = PodStatus(False, "Waiting", ("CrashLoopBackOff", "exit code 1"))


class FakeController:
    """Helm, without Helm."""

    calls: list[tuple[str, object]] = []
    fail_install = False
    fail_uninstall = False
    namespace = "ai-stack"

    def get_pod_labels(self, row):
        return f"app.kubernetes.io/instance=mcpi-{str(row.id)[-8:]}"

    async def install(self, spec):
        FakeController.calls.append(("install", spec))
        if FakeController.fail_install:
            raise RuntimeError("ImagePullBackOff")

    async def upgrade(self, spec):
        FakeController.calls.append(("upgrade", spec))

    async def uninstall(self, instance_id):
        FakeController.calls.append(("uninstall", instance_id))
        if FakeController.fail_uninstall:
            raise RuntimeError("helm is down")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("AIOPS_SECRET_STORE", "memory")
    monkeypatch.setenv("AIOPS_LITELLM_NAMESPACE", "litellm")
    monkeypatch.setenv(
        "AIOPS_LITELLM_POD_LABELS", "app.kubernetes.io/name=litellm"
    )
    monkeypatch.setenv("AIOPS_NAMESPACE", "ai-stack")
    ss._memory.clear()
    FakeController.calls = []
    FakeController.fail_install = FakeController.fail_uninstall = False
    monkeypatch.setattr(deployed, "McpServerController", FakeController)
    yield
    ss._memory.clear()


@pytest.fixture
def env(monkeypatch):
    litellm = mock.Mock()
    litellm.list_mcp_tools.return_value = TOOLS
    litellm.register_mcp_server.side_effect = lambda body: body["server_id"]
    monkeypatch.setattr("api.mcp.litellm_client", lambda: litellm)
    monkeypatch.setattr("api.mcp.org_key", lambda db, user: "sk-org")
    monkeypatch.setattr("api.mcp._team_id", lambda litellm, db, user: "team-1")
    monkeypatch.setattr(
        "utils.mcp_registration.team_id_for_org",
        lambda litellm, db, org_id: "team-1",
    )
    with TestClient(create_app()) as client:
        yield client, litellm
        for server in client.get(SERVERS).json():
            if server.get("deploy"):
                client.delete(f"{SERVERS}/{server['id']}")


def _name():
    return f"graf_{uuid.uuid4().hex[:6]}"


def _deploy(client, headers=None, **overrides):
    body = {
        "catalog": "grafana",
        "name": _name(),
        "settings": {
            "GRAFANA_URL": "http://grafana.monitoring.svc:3000",
            "GRAFANA_SERVICE_ACCOUNT_TOKEN": "glsa_secret",
        },
    }
    body.update(overrides)
    return client.post(INSTANCES, json=body, headers=headers)


def _tick(litellm, instance_id, pods):
    db = get_db_direct()
    try:
        instance = db.get(McpInstance, uuid.UUID(instance_id))
        with mock.patch.object(
            deployed, "get_pod_status_and_readiness", return_value=pods
        ):
            deployed.poll_instance(db, litellm, FakeController(), instance)
    finally:
        db.close()


def _server(client, server_id, headers=None):
    listed = {s["id"]: s for s in client.get(SERVERS, headers=headers).json()}
    return listed.get(server_id)


# --- deploy ------------------------------------------------------------


def test_a_deploy_is_a_server_nobody_can_use_yet(env):
    client, litellm = env
    created = _deploy(client, approval=None)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "deployed" and body["scope"] == "organization"
    # Not the column's default: until the poller registered it, no
    # request may select it and Chat must not turn it on.
    assert body["status"] == "unreachable" and body["tools"] == []
    assert body["approval"] == "writes"
    deploy = body["deploy"]
    assert deploy["status"] == "Pending" and deploy["usable"] is False
    assert deploy["catalog"] == "grafana"
    id8 = deploy["instance_id"][-8:]
    assert body["url"] == f"http://mcpi-{id8}.ai-stack.svc:8000/mcp"
    # Nothing goes to the proxy at create: the pod does not exist.
    litellm.register_mcp_server.assert_not_called()

    ((kind, spec),) = FakeController.calls
    assert kind == "install"
    assert spec.plain == {
        "GRAFANA_URL": "http://grafana.monitoring.svc:3000",
        "READ_ONLY": "true",
    }
    assert spec.env_secret == f"mcpi-{id8}-env"
    assert ss._memory[("ai-stack", f"mcpi-{id8}-env")] == {
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": "glsa_secret"
    }
    assert "glsa_secret" not in created.text
    detail = client.get(f"{INSTANCES}/{deploy['instance_id']}").json()
    assert detail["secret_settings"] == ["GRAFANA_SERVICE_ACCOUNT_TOKEN"]
    assert "glsa_secret" not in str(detail)


def test_who_may_deploy_and_what(env):
    client, _ = env
    assert _deploy(client, ALICE).status_code == 403
    assert _deploy(client, ORGADMIN).status_code == 201
    assert _deploy(client, catalog="nothing").status_code == 404
    assert _deploy(client, name="Bad Name").status_code == 400
    assert _deploy(client, approval="sometimes").status_code == 422
    for settings, text in (
        ({}, "Grafana URL is required"),
        ({"GRAFANA_URL": "http://g", "EXTRA": "x"}, "no setting named EXTRA"),
        ({"GRAFANA_URL": "http://g\nimage: evil"}, "one line"),
    ):
        refused = _deploy(client, settings=settings)
        assert refused.status_code == 422, settings
        assert text in refused.json()["detail"]
    name = _name()
    assert _deploy(client, name=name).status_code == 201
    assert _deploy(client, name=name).status_code == 409
    # A body cannot say where the server is, or what it is.
    smuggled = _deploy(client, source="remote", url="http://evil", image="x")
    assert smuggled.json()["source"] == "deployed"
    assert "evil" not in smuggled.text


def test_a_draft_cannot_be_deployed(env, monkeypatch):
    client, _ = env
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    draft = client.post(
        f"{CATALOG}/import", json={"name": "ai.haymon/database"}
    ).json()
    monkeypatch.delenv("AIOPS_CHAT_MOCK")
    try:
        assert (
            _deploy(client, catalog="database", settings={}).status_code == 404
        )
    finally:
        monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
        client.delete(f"{CATALOG}/{draft['id']}")


def test_no_pod_without_the_rule_that_admits_only_the_proxy(env, monkeypatch):
    client, _ = env
    monkeypatch.delenv("AIOPS_LITELLM_POD_LABELS")
    refused = _deploy(client)
    assert refused.status_code == 503
    assert "every pod" in refused.json()["detail"]
    assert FakeController.calls == []
    monkeypatch.setattr("api.mcp.litellm_client", lambda: None)
    assert _deploy(client).status_code == 503


def test_a_failed_install_keeps_a_failed_row_that_can_be_deleted(env):
    client, litellm = env
    FakeController.fail_install = True
    name = _name()
    failed = _deploy(client, name=name)
    assert failed.status_code == 500
    assert [k for k, _ in FakeController.calls] == ["install", "uninstall"]
    server = next(s for s in client.get(SERVERS).json() if s["name"] == name)
    assert server["deploy"]["status"] == "Failed"
    assert "ImagePullBackOff" in server["deploy"]["last_error"]
    FakeController.fail_uninstall = True
    assert client.delete(f"{SERVERS}/{server['id']}").status_code == 204
    # The proxy is always asked, by the id the platform chose: the row
    # may not know of a registration that was accepted and not committed.
    litellm.delete_mcp_server.assert_called_with(server["id"])


# --- the poller --------------------------------------------------------


def test_the_poller_registers_a_ready_server_once_with_its_own_id(env):
    client, litellm = env
    server = _deploy(client, allowed_tools=["search_dashboards"]).json()
    instance_id = server["deploy"]["instance_id"]

    _tick(litellm, instance_id, STARTING)
    seen = _server(client, server["id"])["deploy"]
    assert seen["launch"]["phase"] == "Pulling image" and not seen["usable"]
    litellm.register_mcp_server.assert_not_called()

    _tick(litellm, instance_id, READY)
    body = litellm.register_mcp_server.call_args.args[0]
    assert body["server_id"] == server["id"]
    assert body["url"] == server["url"] and body["static_headers"] == {}
    assert body["allowed_tools"] == ["search_dashboards"]
    litellm.set_team_mcp_servers.assert_called_with("team-1", mock.ANY)
    assert server["id"] in litellm.set_team_mcp_servers.call_args.args[1]
    seen = _server(client, server["id"])
    assert seen["status"] == "connected"
    assert [t["name"] for t in seen["tools"]] == ["search_dashboards"]
    assert (
        seen["deploy"]["usable"] is True and seen["deploy"]["launch"] is None
    )

    _tick(litellm, instance_id, READY)
    assert litellm.register_mcp_server.call_count == 1


def test_already_exists_is_success_and_a_failure_is_tried_again(env):
    client, litellm = env
    server = _deploy(client).json()
    instance_id = server["deploy"]["instance_id"]
    litellm.register_mcp_server.side_effect = LiteLLMError("down")
    _tick(litellm, instance_id, READY)
    seen = _server(client, server["id"])
    assert seen["status"] == "unreachable" and not seen["deploy"]["usable"]

    # Another replica, or an earlier tick, won the registration: it is
    # this server that exists. An admin narrowed the tools meanwhile (a
    # PATCH skips the proxy while no registration is committed), and the
    # allow-list is enforced in the proxy alone: the body goes again.
    assert (
        client.patch(
            f"{SERVERS}/{server['id']}",
            json={"allowed_tools": ["search_dashboards"]},
        ).status_code
        == 200
    )
    litellm.register_mcp_server.side_effect = LiteLLMError(
        "400", status=400, text="MCP Server with id x already exists."
    )
    _tick(litellm, instance_id, READY)
    assert _server(client, server["id"])["deploy"]["usable"] is True
    sent_id, sent = litellm.update_mcp_server.call_args.args
    assert sent_id == server["id"]
    assert sent["allowed_tools"] == ["search_dashboards"]


def test_a_registration_with_nothing_behind_it_is_not_made(env):
    client, litellm = env
    server = _deploy(client).json()
    # Ready is a TCP check: the endpoint may still refuse.
    litellm.list_mcp_tools.side_effect = LiteLLMError("404 from the server")
    _tick(litellm, server["deploy"]["instance_id"], READY)
    litellm.register_mcp_server.assert_not_called()
    # A delete still asks the proxy, by the id the platform chose, and
    # "not there" is fine.
    litellm.delete_mcp_server.side_effect = LiteLLMError(
        "404", status=404, text="MCP Server not found"
    )
    assert client.delete(f"{SERVERS}/{server['id']}").status_code == 204
    litellm.delete_mcp_server.assert_called_with(server["id"])


def test_a_running_server_renders_what_it_was_deployed_with(env, monkeypatch):
    client, litellm = env
    server = _deploy(client).json()
    instance_id = server["deploy"]["instance_id"]
    _tick(litellm, instance_id, READY)
    entry = next(
        e for e in client.get(CATALOG).json() if e["name"] == "grafana"
    )
    url = f"{CATALOG}/{entry['id']}"
    before = client.get(url).json()
    try:
        # The entry moves on: another port, another argument, a new setting.
        changed = client.patch(
            url,
            json={
                "port": 9999,
                "args": ["--exfiltrate"],
                "settings": [
                    {"name": "NEW_ONE", "label": "New", "required": True}
                ],
            },
        )
        assert changed.status_code == 200, changed.text
        rotated = client.put(
            f"{INSTANCES}/{instance_id}/settings",
            json={"settings": {"GRAFANA_URL": "http://g2:3000"}},
        )
        assert rotated.status_code == 200, rotated.text
        spec = FakeController.calls[-1][1]
        # The URL the proxy knows still fits, and nothing unread runs.
        assert spec.port == 8000 and "--exfiltrate" not in spec.args
        assert [s["name"] for s in spec.schema][0] == "GRAFANA_URL"
        assert rotated.json()["upgrade_available"] is True
        # An explicit upgrade cannot move the port under the registration.
        refused = client.post(f"{INSTANCES}/{instance_id}/upgrade")
        assert refused.status_code == 409
        assert "port or path" in refused.json()["detail"]
    finally:
        client.patch(
            url,
            json={
                "port": before["port"],
                "args": before["args"],
                "settings": before["settings"],
            },
        )


def test_a_team_sync_that_fails_commits_nothing(env):
    client, litellm = env
    server = _deploy(client).json()
    litellm.set_team_mcp_servers.side_effect = LiteLLMError("down")
    _tick(litellm, server["deploy"]["instance_id"], READY)
    seen = _server(client, server["id"])
    # No half state: without the permission the organization's key
    # cannot use the server, so it must not read as connected.
    assert seen["status"] == "unreachable" and not seen["deploy"]["usable"]
    litellm.set_team_mcp_servers.side_effect = None
    _tick(litellm, server["deploy"]["instance_id"], READY)
    assert _server(client, server["id"])["deploy"]["usable"] is True


def test_after_ten_minutes_the_instance_says_what_to_check(env):
    client, litellm = env
    server = _deploy(client).json()
    instance_id = server["deploy"]["instance_id"]
    litellm.register_mcp_server.side_effect = LiteLLMError("timeout")
    _tick(litellm, instance_id, READY)
    assert _server(client, server["id"])["deploy"]["last_error"] is None
    db = get_db_direct()
    try:
        row = db.get(McpInstance, uuid.UUID(instance_id))
        row.ready_since = datetime.now() - timedelta(minutes=11)
        db.commit()
    finally:
        db.close()
    _tick(litellm, instance_id, READY)
    error = _server(client, server["id"])["deploy"]["last_error"]
    assert "the proxy cannot reach it" in error
    assert "AIOPS_LITELLM_POD_LABELS" in error


def test_a_pod_that_goes_down_later_takes_the_server_out(env, monkeypatch):
    client, litellm = env
    server = _deploy(client).json()
    instance_id = server["deploy"]["instance_id"]
    _tick(litellm, instance_id, READY)

    seen = {}

    def relay(*args, **kwargs):
        seen["servers"] = kwargs.get("headers", {}).get("x-mcp-servers")
        raise LiteLLMError("not the point")

    litellm.request.side_effect = relay
    # A Running row whose pod restarts stays "Running": `ready` is what
    # the selection reads.
    _tick(litellm, instance_id, PodStatus(False, "Running"))
    after = _server(client, server["id"])
    assert after["deploy"]["status"] == "Running"
    assert after["status"] == "unreachable" and not after["deploy"]["usable"]
    named = client.post(
        ENDPOINT, json=RPC, headers={"X-Mcp-Servers": server["name"]}
    )
    assert named.status_code == 409
    assert "is not running" in named.json()["detail"]

    _tick(litellm, instance_id, CRASHED)
    crashed = _server(client, server["id"])["deploy"]
    assert crashed["status"] == "Failed"
    assert "CrashLoopBackOff" in crashed["last_error"]
    _tick(litellm, instance_id, READY)
    assert _server(client, server["id"])["deploy"]["usable"] is True
    assert litellm.register_mcp_server.call_count == 1


# --- day two -----------------------------------------------------------


def test_the_registry_guards_what_the_platform_owns(env):
    client, litellm = env
    server = _deploy(client).json()
    url = f"{SERVERS}/{server['id']}"
    for change in (
        {"url": "https://elsewhere.example.com/mcp"},
        {"transport": "sse"},
        {"credential": {"auth_type": "bearer", "value": "x"}},
        {"credential_mode": "shared"},
        {"remove_credential": True},
    ):
        refused = client.patch(url, json=change)
        assert refused.status_code == 409, change
        assert "The platform runs this server" in refused.json()["detail"]
    # Before the registration a PATCH changes the row alone.
    kept = client.patch(
        url, json={"description": "ours", "approval": "always"}
    )
    assert kept.status_code == 200, kept.text
    litellm.update_mcp_server.assert_not_called()
    # A check of a pod that is starting would only write a wrong result.
    assert client.post(f"{url}/refresh").status_code == 409
    _tick(litellm, server["deploy"]["instance_id"], READY)
    assert client.post(f"{url}/refresh").status_code == 200


def test_settings_roll_the_pod_and_a_left_out_secret_stays(env):
    client, litellm = env
    server = _deploy(client).json()
    instance_id = server["deploy"]["instance_id"]
    _tick(litellm, instance_id, READY)
    first = FakeController.calls[0][1].checksum
    url = f"{INSTANCES}/{instance_id}/settings"
    changed = client.put(
        url,
        json={
            "settings": {
                "GRAFANA_URL": "http://other:3000",
                "READ_ONLY": "false",
            }
        },
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["settings"]["GRAFANA_URL"] == "http://other:3000"
    assert body["secret_settings"] == ["GRAFANA_SERVICE_ACCOUNT_TOKEN"]
    assert body["status"] == "Pending" and body["usable"] is False
    kind, spec = FakeController.calls[-1]
    assert kind == "upgrade" and spec.checksum != first
    secret_name = ("ai-stack", spec.env_secret)
    assert ss._memory[secret_name] == {
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": "glsa_secret"
    }
    # Only the secret: the checksum still moves, so the pod rolls.
    before = spec.checksum
    client.put(
        url,
        json={
            "settings": {
                "GRAFANA_URL": "http://other:3000",
                "READ_ONLY": "false",
                "GRAFANA_SERVICE_ACCOUNT_TOKEN": "glsa_rotated",
            }
        },
    )
    assert FakeController.calls[-1][1].checksum != before
    assert (
        ss._memory[secret_name]["GRAFANA_SERVICE_ACCOUNT_TOKEN"]
        == "glsa_rotated"
    )
    # The proxy registration is left alone: the URL did not change.
    assert litellm.register_mcp_server.call_count == 1
    litellm.update_mcp_server.assert_not_called()
    assert (
        client.put(url, json={"settings": {}}, headers=ALICE).status_code
        == 403
    )
    assert (
        client.get(f"{INSTANCES}/{instance_id}", headers=OUTSIDER).status_code
        == 404
    )


def test_delete_is_the_proxy_then_the_release_then_the_rows(env):
    client, litellm = env
    server = _deploy(client).json()
    instance_id = server["deploy"]["instance_id"]
    _tick(litellm, instance_id, READY)
    url = f"{SERVERS}/{server['id']}"

    litellm.delete_mcp_server.side_effect = LiteLLMError("down")
    assert client.delete(url).status_code == 502
    assert _server(client, server["id"])["deploy"]["usable"] is True

    litellm.delete_mcp_server.side_effect = None
    FakeController.fail_uninstall = True
    assert client.delete(url).status_code == 500
    # The true state: a disabled server the proxy does not know, which
    # the poller leaves alone, and which a second Delete finishes.
    half = _server(client, server["id"])
    assert half["enabled"] is False and half["status"] == "unreachable"
    _tick(litellm, instance_id, READY)
    assert litellm.register_mcp_server.call_count == 1

    FakeController.fail_uninstall = False
    assert client.delete(url).status_code == 204
    # One refused call, one accepted, and the second Delete asks again
    # ("not there" would be fine).
    assert litellm.delete_mcp_server.call_count == 3
    assert _server(client, server["id"]) is None
    assert not [k for k in ss._memory if k[1].startswith("mcpi-")]
    db = get_db_direct()
    try:
        # The ORM cascade: SQLite enforces no foreign keys.
        assert db.get(McpInstance, uuid.UUID(instance_id)) is None
        assert db.get(McpServer, uuid.UUID(server["id"])) is None
    finally:
        db.close()


def test_an_entry_in_use_cannot_be_deleted_and_a_deployed_row_is_never_personal(
    env,
):
    client, _ = env
    server = _deploy(client).json()
    entry = next(
        e for e in client.get(CATALOG).json() if e["name"] == "grafana"
    )
    blocked = client.delete(f"{CATALOG}/{entry['id']}")
    assert (
        blocked.status_code == 409 and "deprecate" in blocked.json()["detail"]
    )
    db = get_db_direct()
    try:
        row = db.get(McpServer, uuid.UUID(server["id"]))
        assert row.owner_id is None and row.org_id is not None
    finally:
        db.close()
    # Another organization sees nothing of it.
    assert _server(client, server["id"], OUTSIDER) is None


def test_only_an_admin_reads_the_logs_of_a_deployed_server(env, monkeypatch):
    """The logs can repeat the arguments of other members' tool calls."""
    client, _ = env
    server = _deploy(client).json()
    base = f"{INSTANCES}/{server['deploy']['instance_id']}"
    monkeypatch.setattr(
        "api.instance_inspection.pod_logs",
        lambda *args, **kwargs: {"pods": []},
    )
    monkeypatch.setattr(
        "api.instance_inspection.pod_events", lambda *args, **kwargs: []
    )
    assert client.get(f"{base}/logs").status_code == 200
    assert client.get(f"{base}/logs", headers=ORGADMIN).status_code == 200
    refused = client.get(f"{base}/logs", headers=ALICE)
    assert refused.status_code == 403
    assert "other members" in refused.json()["detail"]
    # Events say nothing of the calls.
    assert client.get(f"{base}/events", headers=ALICE).status_code == 200


def test_the_create_request_of_a_remote_server_has_no_source():
    from schemas.mcp import McpServerCreateRequest

    assert "source" not in McpServerCreateRequest.model_fields


def test_mock_mode_starts_a_server_by_itself(env, monkeypatch):
    client, _ = env
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    monkeypatch.setattr(deployed, "MOCK_START_SECONDS", 0)
    server = _deploy(client).json()
    assert server["deploy"]["launch"]["phase"] == "Starting"
    assert FakeController.calls == []
    seen = _server(client, server["id"])
    assert seen["deploy"]["usable"] is True and seen["tools"]
    failing = _deploy(client, name=f"failing_{uuid.uuid4().hex[:4]}").json()
    assert _server(client, failing["id"])["deploy"]["status"] == "Failed"
