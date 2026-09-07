"""The ext-authz endpoint the gateway calls for every workload request."""

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.authz import _authorize_langflow
from auth.current_user import CurrentUser
from core import create_app
from db.database import get_db_direct
from models.membership import Membership
from models.notebook import Notebook
from models.vectordb_instance import DBVectorDBInstance
from testing.rows import (
    NOTEBOOKS,
    add_row,
    default_org_id,
    delete_rows,
    user_id,
)
from testing.tokens import bearer, make_token
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
        # Langflow is a shared host, not an instance: it parses, and
        # carries no id (#30).
        (f"langflow.{PARENT}", ("langflow", "", "")),
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


def test_member_of_the_resource_organization_is_rescoped(
    oidc_client,  # noqa: F811
    tokens,
    users,
    other_org,  # noqa: F811
):
    """Bob's first membership is ``default``; a vector database in
    ``other`` is authorized as a member of ``other``. Alice is not a
    member there and stays denied."""
    db = get_db_direct()
    try:
        db.add(
            Membership(
                user_id=user_id("bob"),
                org_id=other_org,
                role="member",
                created_at=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()
    vectordb_id = uuid.UUID(
        oidc_client.get("/v1alpha1/vectordb", headers=tokens["alice"]).json()[
            0
        ]["id"]
    )
    instance_id = add_row(
        DBVectorDBInstance(
            vectordb_id=vectordb_id, org_id=other_org, owner_id=user_id("bob")
        )
    )
    try:
        allowed = oidc_client.get(
            ROUTE, headers=tokens["bob"] | host("vdb", instance_id)
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.headers["X-Auth-Org"] == "other"
        assert allowed.headers["X-Auth-User-Sub"] == "bob"
        denied = oidc_client.get(
            ROUTE, headers=tokens["alice"] | host("vdb", instance_id)
        )
        assert denied.status_code == 403
    finally:
        delete_rows(DBVectorDBInstance, instance_id)
        db = get_db_direct()
        try:
            db.query(Membership).filter(
                Membership.user_id == user_id("bob"),
                Membership.org_id == other_org,
            ).delete()
            db.commit()
        finally:
            db.close()


def test_legacy_row_with_no_organization_is_rescoped_to_default(
    oidc_client,  # noqa: F811
    tokens,
    users,
    other_org,  # noqa: F811
):
    """A pre-tenancy row (no org_id) belongs to the default organization
    (auth/policy.py Policy.can_read); a caller currently active in
    another organization is re-scoped back to default when they are
    also a member there."""
    db = get_db_direct()
    try:
        db.add(
            Membership(
                user_id=user_id("bob"),
                org_id=other_org,
                role="member",
                created_at=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()
    legacy = add_row(
        Notebook(
            name="legacy-bob",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
            owner_id=user_id("bob"),
        )
    )
    try:
        # Bob's active organization is "other"; the resource is a legacy
        # row with no organization at all.
        headers = tokens["bob"] | host("nb", legacy) | {"X-Org": "other"}
        allowed = oidc_client.get(ROUTE, headers=headers)
        assert allowed.status_code == 200, allowed.text
        assert allowed.headers["X-Auth-Org"] == "default"
        assert allowed.headers["X-Auth-User-Sub"] == "bob"

        # Alice has no membership in "other", so she reaches this call
        # already active in "default": no re-scope is needed either way.
        denied = oidc_client.get(
            ROUTE, headers=tokens["alice"] | host("nb", legacy)
        )
        assert denied.status_code == 403
    finally:
        delete_rows(Notebook, legacy)
        db = get_db_direct()
        try:
            db.query(Membership).filter(
                Membership.user_id == user_id("bob"),
                Membership.org_id == other_org,
            ).delete()
            db.commit()
        finally:
            db.close()


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


# --- Langflow (#30) ---------------------------------------------------------


LANGFLOW_HOST = {"Host": f"langflow.{PARENT}"}


def test_langflow_is_allowed_for_a_signed_in_member(
    oidc_client,  # noqa: F811
    tokens,
):
    """It is shared, so there is no row to own: any member may open it.
    The point of the check is that the platform decides and logs it,
    where before the gateway let in anyone the realm authenticated."""
    response = oidc_client.get(ROUTE, headers=tokens["alice"] | LANGFLOW_HOST)

    assert response.status_code == 200, response.text
    assert response.headers["X-Auth-User-Sub"] == "alice"
    assert response.headers["X-Auth-Org"]


def test_langflow_subpaths_are_allowed_too(
    oidc_client,  # noqa: F811
    tokens,
):
    """Envoy appends the original method and path, and Langflow is a
    single-page app with its own API and websockets underneath."""
    for method, path in [
        ("GET", ROUTE + "/langflow/ai-stack/x/api/v1/flows"),
        ("POST", ROUTE + "/langflow/ai-stack/x/api/v1/build"),
        ("HEAD", ROUTE + "/"),
    ]:
        response = oidc_client.request(
            method, path, headers=tokens["alice"] | LANGFLOW_HOST
        )
        assert response.status_code == 200, (method, path, response.text)


def test_langflow_is_denied_without_a_token(oidc_client):  # noqa: F811
    response = oidc_client.get(ROUTE, headers=LANGFLOW_HOST)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("auth_kind", "allowed"),
    [
        ("session", True),
        ("dev", True),
        ("token", False),
        ("service", False),
    ],
)
def test_langflow_allows_browser_identities_only(auth_kind, allowed):
    """A personal token and a client-credentials service account belong
    to scripts talking to the API; neither should open a browser
    application. Checked directly on the rule, because minting a token
    here would move the deterministic ids the other tests rely on.
    """
    user = CurrentUser(
        id=uuid.UUID(int=1),
        sub="alice",
        email="alice@example.test",
        name="Alice",
        org_id=uuid.UUID(int=2),
        role="member",
        is_service=auth_kind == "service",
        auth_kind=auth_kind,
    )

    if allowed:
        response = _authorize_langflow(user, f"langflow.{PARENT}", None)
        assert response.status_code == 200
        assert response.headers["X-Auth-User-Sub"] == "alice"
    else:
        with pytest.raises(HTTPException) as excinfo:
            _authorize_langflow(user, f"langflow.{PARENT}", None)
        assert excinfo.value.status_code == 403
        assert "browser" in excinfo.value.detail
