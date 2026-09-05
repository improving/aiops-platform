"""The ext-authz endpoint the gateway calls for every workload request."""

import uuid

import pytest
from fastapi.testclient import TestClient

from core import create_app
from models.notebook import Notebook
from models.vectordb_instance import DBVectorDBInstance
from test_auth import (  # noqa: F401 (fixtures)
    NOTEBOOKS,
    add_row,
    bearer,
    default_org_id,
    delete_rows,
    make_token,
    oidc_client,
    rsa_key,
    user_id,
)
from utils.gateway import id8
from utils.hostnames import parse_hostname

ROUTE = "/v1alpha1/authz/route"
PARENT = "127.0.0.1.nip.io"


@pytest.fixture(autouse=True)
def parent_domain(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", PARENT)


@pytest.fixture
def tokens(rsa_key):  # noqa: F811
    return {
        "alice": bearer(make_token(rsa_key, sub="alice", roles=("member",))),
        "bob": bearer(make_token(rsa_key, sub="bob", roles=("member",))),
        "carol": bearer(make_token(rsa_key, sub="carol", roles=("admin",))),
    }


@pytest.fixture
def users(oidc_client, tokens):  # noqa: F811
    """Make sure the user rows exist before their ids are used as owners."""
    for headers in tokens.values():
        assert oidc_client.get(NOTEBOOKS, headers=headers).status_code == 200


@pytest.fixture
def alices_notebook(users):
    notebook_id = add_row(
        Notebook(
            name="alices",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
            org_id=default_org_id(),
            owner_id=user_id("alice"),
        )
    )
    yield notebook_id
    delete_rows(Notebook, notebook_id)


@pytest.fixture
def bobs_vectordb(oidc_client, tokens, users):  # noqa: F811
    vectordb_id = uuid.UUID(
        oidc_client.get("/v1alpha1/vectordb", headers=tokens["alice"]).json()[
            0
        ]["id"]
    )
    instance_id = add_row(
        DBVectorDBInstance(
            vectordb_id=vectordb_id,
            org_id=default_org_id(),
            owner_id=user_id("bob"),
        )
    )
    yield instance_id
    delete_rows(DBVectorDBInstance, instance_id)


def host(kind, instance_id, suffix=""):
    return {"Host": f"{kind}-{id8(instance_id)}{suffix}.{PARENT}"}


# --- parse_hostname ---------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"nb-1a2b3c4d.{PARENT}", ("nb", "1a2b3c4d", "")),
        (f"vdb-1a2b3c4d.{PARENT}", ("vdb", "1a2b3c4d", "")),
        (f"vdb-1a2b3c4d-api.{PARENT}", ("vdb", "1a2b3c4d", "-api")),
        (f"inf-1a2b3c4d.{PARENT}", ("inf", "1a2b3c4d", "")),
        # The Host header may carry a port and any case.
        (f"NB-1A2B3C4D.{PARENT}:443", ("nb", "1a2b3c4d", "")),
        # A bare label without the parent domain.
        ("nb-1a2b3c4d", ("nb", "1a2b3c4d", "")),
        # Not an instance host, or another domain.
        (f"auth.{PARENT}", None),
        (f"langflow.{PARENT}", None),
        ("nb-1a2b3c4d.other.test", None),
        (f"nb-1a2b3c4.{PARENT}", None),
        (f"nb-1a2b3c4d5.{PARENT}", None),
        (f"nb-1a2b3c4x.{PARENT}", None),
        (f"nb-1a2b3c4d-api.{PARENT}", None),
        (f"inf-1a2b3c4d-api.{PARENT}", None),
        (f"db-1a2b3c4d.{PARENT}", None),
        ("", None),
    ],
)
def test_parse_hostname_with_parent_domain(value, expected):
    assert parse_hostname(value) == expected


def test_parse_hostname_without_settings_reads_the_first_label(monkeypatch):
    monkeypatch.delenv("AIOPS_PARENT_DOMAIN")
    assert parse_hostname("vdb-1a2b3c4d-api.anything.test") == (
        "vdb",
        "1a2b3c4d",
        "-api",
    )
    assert parse_hostname("inf-1a2b3c4d") == ("inf", "1a2b3c4d", "")
    assert parse_hostname("auth.anything.test") is None


# --- decisions --------------------------------------------------------------


def test_subpaths_and_other_methods_are_authorized_too(
    oidc_client,  # noqa: F811
    tokens,
    alices_notebook,
):
    # Envoy forwards the original method and path appended to the ext-authz
    # path, so kernel POSTs and WebSocket upgrades hit sub-paths.
    headers = tokens["alice"] | host("nb", alices_notebook)
    for method, path in [
        ("GET", ROUTE + "/notebook/ai-stack/x/lab"),
        ("POST", ROUTE + "/notebook/ai-stack/x/api/sessions"),
        ("GET", ROUTE + "/notebook/ai-stack/x/api/kernels/1/channels"),
        ("HEAD", ROUTE + "/"),
    ]:
        response = oidc_client.request(method, path, headers=headers)
        assert response.status_code == 200, (method, path, response.text)
        assert response.headers["X-Auth-User-Sub"] == "alice"


def test_owner_is_allowed_with_identity_headers(
    oidc_client,  # noqa: F811
    tokens,
    alices_notebook,
):
    response = oidc_client.get(
        ROUTE, headers=tokens["alice"] | host("nb", alices_notebook)
    )
    assert response.status_code == 200, response.text
    assert response.json() == {}
    assert response.headers["X-Auth-User-Email"] == "alice@example.test"
    assert response.headers["X-Auth-User-Sub"] == "alice"
    assert response.headers["X-Auth-Org"] == "default"


def test_other_member_is_denied_on_a_notebook(
    oidc_client,  # noqa: F811
    tokens,
    alices_notebook,
):
    response = oidc_client.get(
        ROUTE, headers=tokens["bob"] | host("nb", alices_notebook)
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "You do not own this notebook"
    assert "X-Auth-User-Sub" not in response.headers


def test_admin_is_allowed_on_any_notebook(
    oidc_client,  # noqa: F811
    tokens,
    alices_notebook,
):
    response = oidc_client.get(
        ROUTE, headers=tokens["carol"] | host("nb", alices_notebook)
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Auth-User-Sub"] == "carol"


def test_member_is_allowed_on_a_vector_database(
    oidc_client,  # noqa: F811
    tokens,
    bobs_vectordb,
):
    for suffix in ("", "-api"):
        response = oidc_client.get(
            ROUTE, headers=tokens["alice"] | host("vdb", bobs_vectordb, suffix)
        )
        assert response.status_code == 200, response.text
        assert response.headers["X-Auth-User-Sub"] == "alice"


def test_forwarded_host_wins_over_host(
    oidc_client,  # noqa: F811
    tokens,
    alices_notebook,
):
    headers = tokens["bob"] | {
        "Host": f"vdb-deadbeef.{PARENT}",
        "X-Forwarded-Host": f"nb-{id8(alices_notebook)}.{PARENT}, other",
    }
    response = oidc_client.get(ROUTE, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "You do not own this notebook"


def test_unknown_instance_is_404(oidc_client, tokens):  # noqa: F811
    response = oidc_client.get(
        ROUTE, headers=tokens["alice"] | {"Host": f"vdb-deadbeef.{PARENT}"}
    )
    assert response.status_code == 404
    assert "vdb-deadbeef" in response.json()["detail"]


def test_unparsable_host_is_404(oidc_client, tokens):  # noqa: F811
    response = oidc_client.get(
        ROUTE, headers=tokens["alice"] | {"Host": f"auth.{PARENT}"}
    )
    assert response.status_code == 404
    assert isinstance(response.json()["detail"], str)


def test_missing_token_is_401(oidc_client, alices_notebook):  # noqa: F811
    response = oidc_client.get(ROUTE, headers=host("nb", alices_notebook))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_disabled_mode_runs_as_the_dev_admin():
    client = TestClient(create_app())
    # A row from before the tenancy migration: no organization, no owner.
    legacy = add_row(
        Notebook(
            name="legacy",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
        )
    )
    try:
        response = client.get(ROUTE, headers=host("nb", legacy))
        assert response.status_code == 200, response.text
        assert response.headers["X-Auth-User-Sub"] == "dev"
        assert response.headers["X-Auth-User-Email"] == "dev@example.test"
        assert response.headers["X-Auth-Org"] == "default"
    finally:
        delete_rows(Notebook, legacy)
