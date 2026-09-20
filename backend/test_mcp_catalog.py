"""The MCP deploy catalog: the seed, who sees what, and the import of a
registry entry as a draft that a platform admin reviews and publishes.
Mock mode reads the recorded registry entries, so no test needs the
network."""

import json

import pytest
from fastapi.testclient import TestClient

from core import create_app
from db.database import get_db_direct
from db.db import load_mcp_catalog
from models.mcp_catalog import McpCatalogEntry, builtin_id
from paths import BACKEND_DIR

CATALOG = "/v1alpha1/mcp/catalog"
IMPORT = f"{CATALOG}/import"
SEARCH = "/v1alpha1/mcp/registry/search"
ORGADMIN = {"X-Dev-User": "orgadmin"}
ALICE = {"X-Dev-User": "alice"}
IMAGE_ENTRY = "ai.haymon/database"
FIXTURE = json.loads(
    (BACKEND_DIR / "test_fixtures" / "mcp_registry.json").read_text()
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    with TestClient(create_app()) as c:
        yield c
        for entry in c.get(CATALOG).json():
            if entry["source"] != "builtin":
                c.delete(f"{CATALOG}/{entry['id']}")


def test_the_seed_is_published_and_has_a_fixed_id(client):
    listed = {e["name"]: e for e in client.get(CATALOG, headers=ALICE).json()}
    grafana = listed["grafana"]
    assert grafana["status"] == "published" and grafana["source"] == "builtin"
    # Not from genid: a seed row must not move the ids of the snapshots.
    assert grafana["id"] == str(builtin_id("grafana"))
    assert grafana["tag"].startswith("@sha256:")
    token = next(
        s
        for s in grafana["settings"]
        if s["name"] == "GRAFANA_SERVICE_ACCOUNT_TOKEN"
    )
    assert token["secret"] is True and token["default"] is None
    switch = next(s for s in grafana["settings"] if s["name"] == "READ_ONLY")
    assert switch["flag"] == "-disable-write"
    # How an image starts is for the reviewer, not for the list.
    assert "args" not in grafana


def test_an_import_is_a_draft_that_only_a_platform_admin_sees(client):
    created = client.post(IMPORT, json={"name": IMAGE_ENTRY})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft" and body["egress"] == "public"
    assert body["name"] == "database"
    assert (body["image"], body["tag"]) == (
        "ghcr.io/haymon-ai/database",
        "0.7.0",
    )
    assert body["args"][:3] == ["http", "--host", "0.0.0.0"]
    assert any("0.0.0.0" in note for note in body["notes"])

    def names(headers=None):
        return {e["name"] for e in client.get(CATALOG, headers=headers).json()}

    assert "database" in names()
    assert "database" not in names(ORGADMIN)
    assert "database" not in names(ALICE)
    for headers in (ORGADMIN, ALICE):
        assert (
            client.get(f"{CATALOG}/{body['id']}", headers=headers).status_code
            == 403
        )
        assert (
            client.post(
                IMPORT, json={"name": IMAGE_ENTRY}, headers=headers
            ).status_code
            == 403
        )

    published = client.patch(
        f"{CATALOG}/{body['id']}",
        json={"status": "published", "egress": "cluster"},
    )
    assert published.status_code == 200, published.text
    assert "database" in names(ORGADMIN)
    found = client.get(SEARCH, params={"q": "haymon"}).json()
    assert found[0]["already_imported"] is True
    member = client.get(SEARCH, params={"q": "haymon"}, headers=ALICE).json()
    assert member[0]["already_imported"] is False


def test_a_repeat_and_a_taken_name_are_two_different_409s(client):
    assert client.post(IMPORT, json={"name": IMAGE_ENTRY}).status_code == 201
    again = client.post(IMPORT, json={"name": IMAGE_ENTRY})
    assert again.status_code == 409
    assert "imported already" in again.json()["detail"]
    taken = client.post(
        IMPORT, json={"name": "ai.midplane/midplane", "slug": "grafana"}
    )
    assert taken.status_code == 409
    assert "is taken, choose another" in taken.json()["detail"]
    chosen = client.post(
        IMPORT, json={"name": "ai.midplane/midplane", "slug": "pg_gateway"}
    )
    assert chosen.status_code == 201
    assert chosen.json()["name"] == "pg_gateway"
    bad = client.post(
        IMPORT, json={"name": "ai.midplane/midplane", "slug": "Not Valid"}
    )
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("ai.com.mcp/hapi-mcp", "docker run options"),
        ("com.mcparmory/grafana", "stdio"),
        ("ac.inference.sh/mcp", "no container image"),
    ],
)
def test_what_cannot_run_is_refused_at_import(client, name, reason):
    refused = client.post(IMPORT, json={"name": name})
    assert refused.status_code == 422
    assert reason in refused.json()["detail"]


def test_a_review_checks_what_it_changes(client):
    entry = client.post(IMPORT, json={"name": IMAGE_ENTRY}).json()
    url = f"{CATALOG}/{entry['id']}"
    for change in (
        {"path": "/mcp?x=1"},
        {"path": "mcp"},
        {"args": ["ok", "two\nlines"]},
        {"egress": "everything"},
        {"status": "live"},
        {"settings": [{"name": "not a name", "label": "x"}]},
        {"name": "Bad Name"},
    ):
        assert client.patch(url, json=change).status_code == 422, change
    for change in (
        {"settings": [{"name": "LD_PRELOAD", "label": "x"}]},
        {"settings": [{"name": "NODE_OPTIONS", "label": "x"}]},
        {
            "settings": [
                {"name": "SWITCH", "label": "x", "secret": True, "flag": "-x"}
            ]
        },
    ):
        assert client.patch(url, json=change).status_code == 422, change
    # An explicit null is no change, never a 500 or a wrong 409.
    assert (
        client.patch(url, json={"args": None, "title": None}).status_code
        == 200
    )
    renamed = client.patch(url, json={"name": "haymon_db"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "haymon_db"
    assert client.patch(url, json={"name": "grafana"}).status_code == 409
    client.patch(url, json={"status": "published"})
    fixed = client.patch(url, json={"name": "another"})
    assert fixed.status_code == 409
    assert "Only a draft" in fixed.json()["detail"]
    # A secret setting never keeps a default: the catalog goes to members.
    kept = client.patch(
        url,
        json={
            "settings": [
                {
                    "name": "TOKEN",
                    "label": "Token",
                    "secret": True,
                    "default": "x",
                }
            ]
        },
    ).json()
    assert kept["settings"][0]["default"] is None


def test_a_sync_that_changes_what_runs_needs_a_new_review(client, monkeypatch):
    entry = client.post(IMPORT, json={"name": IMAGE_ENTRY}).json()
    url = f"{CATALOG}/{entry['id']}"
    client.patch(url, json={"status": "published", "title": "Our database"})

    same = client.post(f"{url}/sync")
    assert same.status_code == 200 and same.json()["status"] == "published"

    moved = json.loads(json.dumps(FIXTURE))
    for item in moved["servers"]:
        if item["server"]["name"] == IMAGE_ENTRY:
            for package in item["server"]["packages"]:
                package["identifier"] = "ghcr.io/haymon-ai/database:0.8.0"
    fixture = BACKEND_DIR / "tmp" / "mcp_registry_moved.json"
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_text(json.dumps(moved))
    monkeypatch.setattr("api.mcp_catalog.FIXTURE", fixture)

    synced = client.post(f"{url}/sync").json()
    assert synced["tag"] == "0.8.0"
    # Nobody has read 0.8.0: it is not deployable until published again.
    assert synced["status"] == "draft"
    assert synced["notes"][0] == "Sync changed: tag"
    # What an admin wrote by hand stays.
    assert synced["title"] == "Our database"
    assert "database" not in {
        e["name"] for e in client.get(CATALOG, headers=ORGADMIN).json()
    }
    builtin = client.post(f"{CATALOG}/{builtin_id('grafana')}/sync")
    assert builtin.status_code == 409


def test_the_seed_loader_leaves_imported_rows_alone(client, tmp_path):
    taken = client.post(
        IMPORT, json={"name": IMAGE_ENTRY, "slug": "prometheus"}
    ).json()
    seed = tmp_path / "catalog.yaml"
    seed.write_text(
        """
entries:
  - name: prometheus
    title: Builtin Prometheus
    image: docker.io/acme/prometheus-mcp
    tag: "1.0.0"
    port: 8000
    chart_repo: https://infracloudio.github.io/charts
    chart_name: mcp-server
"""
    )
    db = get_db_direct()
    try:
        # A taken name is skipped, never a startup error.
        load_mcp_catalog(db, path=seed)
        rows = db.query(McpCatalogEntry).filter_by(name="prometheus").all()
        assert [str(r.id) for r in rows] == [taken["id"]]
        assert rows[0].title != "Builtin Prometheus"
    finally:
        db.close()
