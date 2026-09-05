"""Workload credentials: the Secrets, the row and the one-time reveal.

The Kubernetes CoreV1 client is mocked at ``utils.credentials``; the
router tests use the same oidc fixture pattern as ``test_auth.py`` so
that a member (not the dev admin) owns the instance.
"""

import base64
import time
import uuid
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from auth import jwt as auth_jwt
from core import create_app
from db.database import get_db_direct
from models.inference_instance import DBInferenceInstance
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.user import User
from models.vectordb_instance import DBVectorDBInstance
from models.workload_credential import WorkloadCredential
from utils import credentials

ISSUER = "https://issuer.invalid/realms/test"
AUDIENCE = "aiops-api"
KID = "test-key"
NAMESPACE = "ai-stack"
NOTEBOOKS = "/v1alpha1/notebooks"

# Fixed ids: rows created with them consume no genid counter, so the
# ids the snapshot tests expect do not shift. id8 is the last eight
# hex characters.
VDB_ID = uuid.UUID("c0ffee00-0000-4000-8000-00000000abcd")
INF_ID = uuid.UUID("c0ffee00-0000-4000-8000-00000000ef01")
VDB_SECRET = "vdb-0000abcd-credentials"
VDB_APIKEY_SECRET = "vdb-0000abcd-apikey-auth"
VDB_URL = f"/v1alpha1/credentials/vdb/{VDB_ID}"
INF_URL = f"/v1alpha1/credentials/inf/{INF_ID}"


# --- fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def schema():
    """The unit tests use the session directly; run the migrations once."""
    create_app()


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def oidc_client(monkeypatch, rsa_key):
    """A TestClient in oidc mode whose JWKS is the test key."""
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    jwks = {"keys": [RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True)]}
    jwks["keys"][0]["kid"] = KID
    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda self: jwks)
    auth_jwt.reset_jwks_client()
    yield TestClient(create_app())
    auth_jwt.reset_jwks_client()


def make_token(key, sub, roles):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": sub,
        "azp": "aiops-ui",
        "iat": now,
        "exp": now + 300,
        "email": f"{sub}@example.test",
        "name": sub.capitalize(),
        "realm_access": {"roles": list(roles)},
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tokens(rsa_key):
    return {
        "alice": bearer(make_token(rsa_key, "alice", ("member",))),
        "bob": bearer(make_token(rsa_key, "bob", ("member",))),
        "carol": bearer(make_token(rsa_key, "carol", ("admin",))),
    }


@pytest.fixture
def core_v1():
    """The mocked CoreV1 API every credential helper talks to."""
    with mock.patch("utils.credentials.get_core_v1_client") as get_client:
        yield get_client.return_value


def default_org_id(db):
    return (
        db.query(Organization)
        .filter(Organization.slug == DEFAULT_ORG_SLUG)
        .one()
        .id
    )


def user_id(db, sub):
    return db.query(User).filter(User.sub == sub).one().id


def credential_row(kind, resource_id):
    db = get_db_direct()
    try:
        return (
            db.query(WorkloadCredential)
            .filter(
                WorkloadCredential.resource_kind == kind,
                WorkloadCredential.resource_id == resource_id,
            )
            .first()
        )
    finally:
        db.close()


def delete_credential_rows(*resource_ids):
    db = get_db_direct()
    try:
        db.query(WorkloadCredential).filter(
            WorkloadCredential.resource_id.in_(resource_ids)
        ).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def clean_rows():
    """Remove the credential rows a unit test leaves behind."""
    yield
    delete_credential_rows(VDB_ID, INF_ID)


@pytest.fixture
def instances(oidc_client, tokens):
    """A vector database and an inference instance owned by alice."""
    # alice and bob get their user rows on their first request.
    for who in ("alice", "bob"):
        assert (
            oidc_client.get(NOTEBOOKS, headers=tokens[who]).status_code == 200
        )
    db = get_db_direct()
    try:
        org_id = default_org_id(db)
        owner_id = user_id(db, "alice")
        db.add(DBVectorDBInstance(id=VDB_ID, org_id=org_id, owner_id=owner_id))
        db.add(
            DBInferenceInstance(id=INF_ID, org_id=org_id, owner_id=owner_id)
        )
        db.commit()
    finally:
        db.close()
    yield
    delete_credential_rows(VDB_ID, INF_ID)
    db = get_db_direct()
    try:
        db.query(DBVectorDBInstance).filter(
            DBVectorDBInstance.id == VDB_ID
        ).delete()
        db.query(DBInferenceInstance).filter(
            DBInferenceInstance.id == INF_ID
        ).delete()
        db.commit()
    finally:
        db.close()


def store(kind, resource_id, value):
    db = get_db_direct()
    try:
        return credentials.store_credential(
            db, NAMESPACE, kind, resource_id, value
        )
    finally:
        db.close()


def secret_with(value):
    encoded = base64.b64encode(value.encode()).decode()
    return client.V1Secret(data={"api-key": encoded})


def created_bodies(core_v1):
    calls = core_v1.create_namespaced_secret.call_args_list
    assert {c.kwargs["namespace"] for c in calls} == {NAMESPACE}
    return {c.kwargs["body"].metadata.name: c.kwargs["body"] for c in calls}


# --- generate_secret --------------------------------------------------------


def test_generate_secret_is_deterministic_under_test_mode():
    value = credentials.generate_secret(seed=str(VDB_ID))
    assert value == credentials.generate_secret(seed=str(VDB_ID))
    assert value != credentials.generate_secret(seed=str(INF_ID))
    # Same shape as secrets.token_urlsafe(32): 32 bytes, no padding.
    assert "=" not in value
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    assert len(raw) == 32
    shorter = credentials.generate_secret(16, seed=str(VDB_ID))
    assert len(shorter) < len(value)


def test_generate_secret_is_random_outside_test_mode(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "false")
    first = credentials.generate_secret(seed="fixed")
    assert first != credentials.generate_secret(seed="fixed")
    assert len(first) >= 43


def test_generate_secret_without_a_seed_is_random():
    assert credentials.generate_secret() != credentials.generate_secret()


def test_credential_secret_names():
    assert credentials.credential_secret_names("vdb", VDB_ID) == (
        VDB_SECRET,
        VDB_APIKEY_SECRET,
    )
    assert credentials.credential_secret_names("inf", INF_ID) == (
        "inf-0000ef01-credentials",
        "inf-0000ef01-apikey-auth",
    )


# --- store_credential / delete_credential -----------------------------------


def test_store_credential_creates_both_secrets_and_the_row(
    core_v1, clean_rows
):
    row = store("vdb", VDB_ID, "s3cret")

    assert row.resource_kind == "vdb"
    assert row.resource_id == VDB_ID
    assert row.namespace == NAMESPACE
    assert row.secret_name == VDB_SECRET
    assert row.apikey_secret_name == VDB_APIKEY_SECRET
    assert row.created_at is not None
    assert row.shown_at is None

    bodies = created_bodies(core_v1)
    assert set(bodies) == {VDB_SECRET, VDB_APIKEY_SECRET}
    assert bodies[VDB_SECRET].string_data == {"api-key": "s3cret"}
    assert bodies[VDB_APIKEY_SECRET].string_data == {str(VDB_ID): "s3cret"}
    for body in bodies.values():
        assert body.metadata.namespace == NAMESPACE
        assert body.metadata.labels == {
            "app.kubernetes.io/managed-by": "aiops"
        }
    core_v1.replace_namespaced_secret.assert_not_called()
    assert credential_row("vdb", VDB_ID).id == row.id


def test_store_credential_replaces_existing_secrets(core_v1, clean_rows):
    core_v1.create_namespaced_secret.side_effect = [
        None,
        None,
        ApiException(status=409),
        ApiException(status=409),
    ]
    first = store("vdb", VDB_ID, "s3cret")
    second = store("vdb", VDB_ID, "r0tated")

    assert second.id == first.id
    replaced = core_v1.replace_namespaced_secret.call_args_list
    assert {c.kwargs["name"] for c in replaced} == {
        VDB_SECRET,
        VDB_APIKEY_SECRET,
    }
    assert {c.kwargs["namespace"] for c in replaced} == {NAMESPACE}
    for c in replaced:
        assert c.kwargs["body"].metadata.name == c.kwargs["name"]
        assert list(c.kwargs["body"].string_data.values()) == ["r0tated"]
    db = get_db_direct()
    try:
        assert (
            db.query(WorkloadCredential)
            .filter(WorkloadCredential.resource_id == VDB_ID)
            .count()
            == 1
        )
    finally:
        db.close()


def test_store_credential_writes_no_row_when_the_secret_fails(
    core_v1, clean_rows
):
    core_v1.create_namespaced_secret.side_effect = ApiException(status=500)
    with pytest.raises(ApiException):
        store("vdb", VDB_ID, "s3cret")
    assert credential_row("vdb", VDB_ID) is None


def test_delete_credential_swallows_404(core_v1, clean_rows):
    store("inf", INF_ID, "s3cret")
    core_v1.delete_namespaced_secret.side_effect = ApiException(status=404)

    db = get_db_direct()
    try:
        credentials.delete_credential(db, NAMESPACE, "inf", INF_ID)
    finally:
        db.close()

    deleted = core_v1.delete_namespaced_secret.call_args_list
    assert {c.kwargs["name"] for c in deleted} == {
        "inf-0000ef01-credentials",
        "inf-0000ef01-apikey-auth",
    }
    assert credential_row("inf", INF_ID) is None


def test_delete_credential_without_a_row_is_a_no_op(core_v1):
    db = get_db_direct()
    try:
        credentials.delete_credential(db, NAMESPACE, "inf", INF_ID)
    finally:
        db.close()
    assert core_v1.delete_namespaced_secret.call_count == 2


def test_delete_credential_raises_other_errors(core_v1, clean_rows):
    store("inf", INF_ID, "s3cret")
    core_v1.delete_namespaced_secret.side_effect = ApiException(status=500)
    db = get_db_direct()
    try:
        with pytest.raises(ApiException):
            credentials.delete_credential(db, NAMESPACE, "inf", INF_ID)
    finally:
        db.close()
    assert credential_row("inf", INF_ID) is not None


# --- GET /v1alpha1/credentials/{kind}/{resource_id} -------------------------


def test_first_read_reveals_then_hides(
    oidc_client, tokens, core_v1, instances
):
    store("vdb", VDB_ID, "s3cret")
    core_v1.read_namespaced_secret.return_value = secret_with("s3cret")

    first = oidc_client.get(VDB_URL, headers=tokens["alice"])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["key"] == "api-key"
    assert body["value"] == "s3cret"
    assert body["shown_at"] is not None
    core_v1.read_namespaced_secret.assert_called_once_with(
        name=VDB_SECRET, namespace=NAMESPACE
    )
    assert credential_row("vdb", VDB_ID).shown_at is not None

    second = oidc_client.get(VDB_URL, headers=tokens["alice"])
    assert second.status_code == 200, second.text
    assert second.json() == {
        "key": "api-key",
        "value": None,
        "shown_at": body["shown_at"],
    }
    # The hidden path does not touch the cluster.
    core_v1.read_namespaced_secret.assert_called_once()


def test_reveal_is_for_admins_only(oidc_client, tokens, core_v1, instances):
    store("vdb", VDB_ID, "s3cret")
    core_v1.read_namespaced_secret.return_value = secret_with("s3cret")
    shown = oidc_client.get(VDB_URL, headers=tokens["alice"]).json()
    assert shown["value"] == "s3cret"

    owner = oidc_client.get(f"{VDB_URL}?reveal=true", headers=tokens["alice"])
    assert owner.status_code == 200
    assert owner.json()["value"] is None

    admin = oidc_client.get(VDB_URL, headers=tokens["carol"])
    assert admin.status_code == 200
    assert admin.json()["value"] is None

    revealed = oidc_client.get(
        f"{VDB_URL}?reveal=true", headers=tokens["carol"]
    )
    assert revealed.status_code == 200, revealed.text
    assert revealed.json() == {
        "key": "api-key",
        "value": "s3cret",
        "shown_at": shown["shown_at"],
    }


def test_non_owner_is_403(oidc_client, tokens, core_v1, instances):
    store("vdb", VDB_ID, "s3cret")
    denied = oidc_client.get(VDB_URL, headers=tokens["bob"])
    assert denied.status_code == 403
    assert (
        denied.json()["detail"]
        == "You do not own this vector database instance"
    )
    core_v1.read_namespaced_secret.assert_not_called()
    assert credential_row("vdb", VDB_ID).shown_at is None


def test_inference_credential_is_read_the_same_way(
    oidc_client, tokens, core_v1, instances
):
    store("inf", INF_ID, "1nf")
    core_v1.read_namespaced_secret.return_value = secret_with("1nf")
    response = oidc_client.get(INF_URL, headers=tokens["alice"])
    assert response.status_code == 200, response.text
    assert response.json()["value"] == "1nf"
    core_v1.read_namespaced_secret.assert_called_once_with(
        name="inf-0000ef01-credentials", namespace=NAMESPACE
    )
    denied = oidc_client.get(INF_URL, headers=tokens["bob"])
    assert denied.json()["detail"] == "You do not own this inference instance"


def test_missing_credential_is_404(oidc_client, tokens, core_v1, instances):
    response = oidc_client.get(VDB_URL, headers=tokens["alice"])
    assert response.status_code == 404
    assert "credential" in response.json()["detail"]


def test_unknown_instance_is_404(oidc_client, tokens, core_v1):
    response = oidc_client.get(
        f"/v1alpha1/credentials/vdb/{uuid.uuid4()}", headers=tokens["alice"]
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Vector database instance not found"


def test_unknown_kind_is_422(oidc_client, tokens):
    response = oidc_client.get(
        f"/v1alpha1/credentials/nb/{VDB_ID}", headers=tokens["alice"]
    )
    assert response.status_code == 422


def test_credential_needs_a_token(oidc_client):
    assert oidc_client.get(VDB_URL).status_code == 401


def test_missing_secret_keeps_the_reveal(
    oidc_client, tokens, core_v1, instances
):
    store("vdb", VDB_ID, "s3cret")
    core_v1.read_namespaced_secret.side_effect = ApiException(status=404)
    response = oidc_client.get(VDB_URL, headers=tokens["alice"])
    assert response.status_code == 404
    assert VDB_SECRET in response.json()["detail"]
    assert credential_row("vdb", VDB_ID).shown_at is None


def test_unreachable_cluster_is_503_and_keeps_the_reveal(
    oidc_client, tokens, core_v1, instances
):
    store("vdb", VDB_ID, "s3cret")
    core_v1.read_namespaced_secret.side_effect = ApiException(status=500)
    response = oidc_client.get(VDB_URL, headers=tokens["alice"])
    assert response.status_code == 503
    assert isinstance(response.json()["detail"], str)
    assert credential_row("vdb", VDB_ID).shown_at is None


def test_membership_rows_exist_for_the_test_users(oidc_client, tokens):
    # Guards the fixture assumption that alice is a member, not an admin.
    oidc_client.get(NOTEBOOKS, headers=tokens["alice"])
    db = get_db_direct()
    try:
        role = (
            db.query(Membership)
            .filter(Membership.user_id == user_id(db, "alice"))
            .one()
            .role
        )
    finally:
        db.close()
    assert role == "member"
