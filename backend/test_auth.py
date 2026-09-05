import time
import uuid
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientConnectionError

from auth import jwt as auth_jwt
from core import create_app
from db.database import get_db_direct
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.user import User

ISSUER = "https://issuer.invalid/realms/test"
AUDIENCE = "aiops-api"
KID = "test-key"

NOTEBOOKS = "/v1alpha1/notebooks"
MODELS = "/v1alpha1/models"


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


def make_token(
    key,
    sub="alice",
    email="alice@example.test",
    name="Alice",
    roles=("member",),
    azp="aiops-ui",
    aud=AUDIENCE,
    iss=ISSUER,
    expires_in=300,
    kid=KID,
):
    now = int(time.time())
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "azp": azp,
        "iat": now,
        "exp": now + expires_in,
        "realm_access": {"roles": list(roles)},
    }
    if email is not None:
        claims["email"] = email
    if name is not None:
        claims["name"] = name
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def membership_of(sub):
    db = get_db_direct()
    try:
        user = db.query(User).filter(User.sub == sub).one()
        org = (
            db.query(Organization)
            .filter(Organization.slug == DEFAULT_ORG_SLUG)
            .one()
        )
        membership = (
            db.query(Membership)
            .filter(Membership.user_id == user.id, Membership.org_id == org.id)
            .one()
        )
        return user, membership
    finally:
        db.close()


def assert_unauthorized(response):
    assert response.status_code == 401, response.text
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert isinstance(response.json()["detail"], str)


# --- tokens -----------------------------------------------------------------


def test_missing_token_is_401(oidc_client):
    assert_unauthorized(oidc_client.get(NOTEBOOKS))


def test_non_bearer_scheme_is_401(oidc_client):
    response = oidc_client.get(
        NOTEBOOKS, headers={"Authorization": "Basic YWxpY2U6cHc="}
    )
    assert_unauthorized(response)


def test_health_needs_no_token(oidc_client):
    assert oidc_client.get("/health").status_code == 200


def test_valid_token_upserts_user_and_membership(oidc_client, rsa_key):
    response = oidc_client.get(NOTEBOOKS, headers=bearer(make_token(rsa_key)))
    assert response.status_code == 200, response.text
    user, membership = membership_of("alice")
    assert user.email == "alice@example.test"
    assert user.name == "Alice"
    assert user.last_seen_at is not None
    assert membership.role == "member"

    # A second token for the same subject updates the row in place.
    renamed = make_token(rsa_key, name="Alice Liddell")
    assert (
        oidc_client.get(NOTEBOOKS, headers=bearer(renamed)).status_code == 200
    )
    user, _ = membership_of("alice")
    assert user.name == "Alice Liddell"
    db = get_db_direct()
    try:
        assert db.query(User).filter(User.sub == "alice").count() == 1
    finally:
        db.close()


def test_expired_token_is_401(oidc_client, rsa_key):
    # Past the 60 second leeway.
    token = make_token(rsa_key, expires_in=-120)
    assert_unauthorized(oidc_client.get(NOTEBOOKS, headers=bearer(token)))


def test_wrong_audience_is_401(oidc_client, rsa_key):
    token = make_token(rsa_key, aud="other-api")
    assert_unauthorized(oidc_client.get(NOTEBOOKS, headers=bearer(token)))


def test_wrong_issuer_is_401(oidc_client, rsa_key):
    token = make_token(rsa_key, iss="https://issuer.invalid/realms/other")
    assert_unauthorized(oidc_client.get(NOTEBOOKS, headers=bearer(token)))


def test_unknown_key_is_401(oidc_client, rsa_key):
    token = make_token(rsa_key, kid="rotated")
    assert_unauthorized(oidc_client.get(NOTEBOOKS, headers=bearer(token)))


def test_garbage_token_is_401(oidc_client):
    assert_unauthorized(
        oidc_client.get(NOTEBOOKS, headers=bearer("not.a.jwt"))
    )


def test_unreachable_jwks_is_503(oidc_client, rsa_key, monkeypatch):
    def boom(self):
        raise PyJWKClientConnectionError("connection refused")

    monkeypatch.setattr(PyJWKClient, "fetch_data", boom)
    auth_jwt.reset_jwks_client()
    response = oidc_client.get(NOTEBOOKS, headers=bearer(make_token(rsa_key)))
    assert response.status_code == 503
    assert "identity provider" in response.json()["detail"]


def test_admin_role_comes_from_realm_roles(oidc_client, rsa_key):
    token = make_token(rsa_key, sub="carol", roles=("admin", "member"))
    assert oidc_client.get(NOTEBOOKS, headers=bearer(token)).status_code == 200
    _, membership = membership_of("carol")
    assert membership.role == "admin"


def test_role_change_updates_membership(oidc_client, rsa_key):
    member = make_token(rsa_key, sub="dave", roles=("member",))
    admin = make_token(rsa_key, sub="dave", roles=("admin",))
    oidc_client.get(NOTEBOOKS, headers=bearer(member))
    assert membership_of("dave")[1].role == "member"
    oidc_client.get(NOTEBOOKS, headers=bearer(admin))
    assert membership_of("dave")[1].role == "admin"


def test_utility_endpoints_require_admin(oidc_client, rsa_key):
    member = make_token(rsa_key, roles=("member",))
    admin = make_token(rsa_key, sub="carol", roles=("admin",))
    with mock.patch("core.reload_data") as reload_data:
        denied = oidc_client.post("/reload-data", headers=bearer(member))
        assert denied.status_code == 403
        assert "admin" in denied.json()["detail"]
        reload_data.assert_not_called()
        allowed = oidc_client.post("/reload-data", headers=bearer(admin))
        assert allowed.status_code == 200, allowed.text
        reload_data.assert_called_once()
    with mock.patch("core.refresh_db") as refresh_db:
        assert (
            oidc_client.post("/refresh-db", headers=bearer(member)).status_code
            == 403
        )
        refresh_db.assert_not_called()


def test_viewer_cannot_post(oidc_client, rsa_key):
    viewer = make_token(rsa_key, sub="eve", roles=())
    assert oidc_client.get(MODELS, headers=bearer(viewer)).status_code == 200
    assert membership_of("eve")[1].role == "viewer"
    response = oidc_client.post(
        MODELS,
        json={
            "name": "viewer-model",
            "modelId": "viewer/model",
            "description": "",
            "category": "llm",
            "subcategory": "text generation",
            "size": 1,
            "countAdapters": 0,
        },
        headers=bearer(viewer),
    )
    assert response.status_code == 403
    assert isinstance(response.json()["detail"], str)


def test_client_credentials_token_maps_to_service_user(oidc_client, rsa_key):
    token = make_token(
        rsa_key,
        sub="4c2f8f9e-0000-4000-8000-000000000042",
        email=None,
        name=None,
        roles=(),
        azp="aiops-automation",
    )
    assert oidc_client.get(NOTEBOOKS, headers=bearer(token)).status_code == 200
    user, membership = membership_of("svc:aiops-automation")
    assert user.email is None
    assert membership.role == "member"


# --- modes ------------------------------------------------------------------


def test_disabled_mode_needs_test_mode(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    with pytest.raises(
        RuntimeError, match="AUTH_MODE=disabled requires TEST_MODE=true"
    ):
        create_app(setup_db=False)


def test_oidc_mode_needs_an_issuer(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    with pytest.raises(RuntimeError, match="OIDC_ISSUER"):
        create_app(setup_db=False)


def test_unknown_auth_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "maybe")
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        create_app(setup_db=False)


def test_disabled_mode_runs_as_the_dev_admin():
    client = TestClient(create_app())
    assert client.get(NOTEBOOKS).status_code == 200
    user, membership = membership_of("dev")
    assert user.email == "dev@example.test"
    assert membership.role == "admin"
    with mock.patch("core.reload_data"):
        assert client.post("/reload-data").status_code == 200


# --- ownership --------------------------------------------------------------


NOT_READY = (False, "Pending")


def notebook_payload(name):
    return {
        "name": name,
        "type": "vscode",
        "framework": "python",
        "nvidia_gpu": False,
    }


@pytest.fixture
def notebook_controller(monkeypatch):
    with mock.patch("api.notebooks.NotebooksController") as controller_cls:
        controller = controller_cls.return_value
        controller.install = mock.AsyncMock()
        controller.upgrade = mock.AsyncMock()
        controller.uninstall = mock.AsyncMock()
        monkeypatch.setattr(
            "api.notebooks.get_pod_status_and_readiness",
            lambda *args: NOT_READY,
        )
        yield controller


@pytest.fixture
def tokens(rsa_key):
    return {
        "alice": bearer(make_token(rsa_key, sub="alice", roles=("member",))),
        "bob": bearer(make_token(rsa_key, sub="bob", roles=("member",))),
        "carol": bearer(make_token(rsa_key, sub="carol", roles=("admin",))),
    }


@pytest.fixture
def other_org():
    """A second organization; rows added to it are removed afterwards."""
    from models.finetune import DBFinetune
    from models.inference_instance import DBInferenceInstance
    from models.model_adapters import DBModelAdapters
    from models.notebook import Notebook
    from models.vectordb_instance import DBVectorDBInstance

    db = get_db_direct()
    org = Organization(slug="other", name="Other")
    db.add(org)
    db.commit()
    org_id = org.id
    db.close()
    yield org_id
    db = get_db_direct()
    for model in (
        Notebook,
        DBVectorDBInstance,
        DBInferenceInstance,
        DBFinetune,
        DBModelAdapters,
    ):
        db.query(model).filter(model.org_id == org_id).delete()
    db.query(Organization).filter(Organization.id == org_id).delete()
    db.commit()
    db.close()


def default_org_id():
    db = get_db_direct()
    try:
        return (
            db.query(Organization)
            .filter(Organization.slug == DEFAULT_ORG_SLUG)
            .one()
            .id
        )
    finally:
        db.close()


def user_id(sub):
    return membership_of(sub)[0].id


def add_row(row):
    db = get_db_direct()
    try:
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def delete_rows(model, *ids):
    db = get_db_direct()
    try:
        db.query(model).filter(model.id.in_(ids)).delete()
        db.commit()
    finally:
        db.close()


def test_create_notebook_sets_org_and_owner(
    oidc_client, tokens, notebook_controller
):
    from models.notebook import Notebook

    created = oidc_client.post(
        NOTEBOOKS, json=notebook_payload("owned"), headers=tokens["alice"]
    )
    assert created.status_code == 200, created.text
    notebook_id = created.json()["id"]
    db = get_db_direct()
    try:
        row = db.get(Notebook, uuid.UUID(notebook_id))
        assert row.org_id == default_org_id()
        assert row.owner_id == user_id("alice")
    finally:
        db.close()
    deleted = oidc_client.delete(
        f"{NOTEBOOKS}/{notebook_id}", headers=tokens["alice"]
    )
    assert deleted.status_code == 200, deleted.text


def test_notebooks_are_scoped_to_the_organization(
    oidc_client, tokens, notebook_controller, other_org
):
    from models.notebook import Notebook

    mine = oidc_client.post(
        NOTEBOOKS, json=notebook_payload("mine"), headers=tokens["alice"]
    ).json()["id"]
    theirs = add_row(
        Notebook(
            name="theirs",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
            org_id=other_org,
        )
    )
    # A row from before the tenancy migration: no organization, no owner.
    legacy = add_row(
        Notebook(
            name="legacy",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
        )
    )

    listed = oidc_client.get(NOTEBOOKS, headers=tokens["alice"])
    assert listed.status_code == 200, listed.text
    # Notebooks are personal: a member sees only their own; the legacy row
    # (no owner) and everything else in the organization is for admins.
    assert {n["name"] for n in listed.json()} == {"mine"}
    admin_listed = oidc_client.get(NOTEBOOKS, headers=tokens["carol"])
    assert {"mine", "legacy"} <= {n["name"] for n in admin_listed.json()}
    assert "theirs" not in {n["name"] for n in admin_listed.json()}

    forbidden = oidc_client.get(
        f"{NOTEBOOKS}/{theirs}", headers=tokens["alice"]
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "You do not own this notebook"

    # Legacy rows have no owner: only admins may read or write them.
    assert (
        oidc_client.get(
            f"{NOTEBOOKS}/{legacy}", headers=tokens["bob"]
        ).status_code
        == 403
    )
    assert (
        oidc_client.delete(
            f"{NOTEBOOKS}/{legacy}", headers=tokens["bob"]
        ).status_code
        == 403
    )
    assert (
        oidc_client.delete(
            f"{NOTEBOOKS}/{legacy}", headers=tokens["carol"]
        ).status_code
        == 200
    )
    assert (
        oidc_client.delete(
            f"{NOTEBOOKS}/{mine}", headers=tokens["alice"]
        ).status_code
        == 200
    )


def test_other_member_cannot_write_a_notebook(
    oidc_client, tokens, notebook_controller
):
    created = oidc_client.post(
        NOTEBOOKS, json=notebook_payload("alices"), headers=tokens["alice"]
    )
    assert created.status_code == 200, created.text
    url = f"{NOTEBOOKS}/{created.json()['id']}"

    # Notebooks are personal: another member sees neither the row nor the list entry.
    bobs_get = oidc_client.get(url, headers=tokens["bob"])
    assert bobs_get.status_code == 403
    assert bobs_get.json()["detail"] == "You do not own this notebook"
    listed_for = {
        who: [
            n["id"]
            for n in oidc_client.get(NOTEBOOKS, headers=tokens[who]).json()
        ]
        for who in ("alice", "bob", "carol")
    }
    assert created.json()["id"] in listed_for["alice"]
    assert created.json()["id"] not in listed_for["bob"]
    assert created.json()["id"] in listed_for["carol"]  # org admin
    updated = oidc_client.put(url, json=created.json(), headers=tokens["bob"])
    assert updated.status_code == 403
    assert updated.json()["detail"] == "You do not own this notebook"
    notebook_controller.upgrade.assert_not_awaited()
    assert oidc_client.delete(url, headers=tokens["bob"]).status_code == 403
    notebook_controller.uninstall.assert_not_awaited()

    # The owner and the organization admin may write.
    assert (
        oidc_client.put(
            url, json=created.json(), headers=tokens["alice"]
        ).status_code
        == 200
    )
    assert oidc_client.delete(url, headers=tokens["carol"]).status_code == 200
    notebook_controller.uninstall.assert_awaited_once()


def test_vectordb_instances_are_scoped(
    oidc_client, tokens, other_org, monkeypatch
):
    from models.vectordb_instance import DBVectorDBInstance

    monkeypatch.setattr(
        "api.vectordb_instance.check_pod_status_and_readiness",
        lambda instance: NOT_READY,
    )
    vectordb_id = uuid.UUID(
        oidc_client.get("/v1alpha1/vectordb", headers=tokens["alice"]).json()[
            0
        ]["id"]
    )
    # Make sure bob exists before his id is used as an owner.
    oidc_client.get(NOTEBOOKS, headers=tokens["bob"])
    bobs = add_row(
        DBVectorDBInstance(
            vectordb_id=vectordb_id,
            org_id=default_org_id(),
            owner_id=user_id("bob"),
        )
    )
    add_row(DBVectorDBInstance(vectordb_id=vectordb_id, org_id=other_org))
    url = f"/v1alpha1/vectordb_instances/{bobs}"
    try:
        listed = oidc_client.get(
            "/v1alpha1/vectordb_instances", headers=tokens["alice"]
        )
        assert listed.status_code == 200, listed.text
        assert [i["id"] for i in listed.json()] == [str(bobs)]
        assert oidc_client.get(url, headers=tokens["alice"]).status_code == 200
        denied = oidc_client.delete(url, headers=tokens["alice"])
        assert denied.status_code == 403
        assert (
            denied.json()["detail"]
            == "You do not own this vector database instance"
        )
    finally:
        delete_rows(DBVectorDBInstance, bobs)


def test_inference_instances_are_scoped(
    oidc_client, tokens, other_org, monkeypatch
):
    from models.inference_instance import DBInferenceInstance

    monkeypatch.setattr(
        "api.inference_instance.check_pod_status_and_readiness",
        lambda instance, db: NOT_READY,
    )
    model_id = uuid.UUID(
        oidc_client.get(MODELS, headers=tokens["alice"]).json()[0]["id"]
    )
    engine_id = uuid.UUID(
        oidc_client.get("/v1alpha1/engines", headers=tokens["alice"]).json()[
            0
        ]["id"]
    )
    oidc_client.get(NOTEBOOKS, headers=tokens["bob"])
    bobs = add_row(
        DBInferenceInstance(
            model_id=model_id,
            engine_id=engine_id,
            org_id=default_org_id(),
            owner_id=user_id("bob"),
        )
    )
    add_row(
        DBInferenceInstance(
            model_id=model_id, engine_id=engine_id, org_id=other_org
        )
    )
    url = f"/v1alpha1/inferenceInstance/{bobs}"
    try:
        listed = oidc_client.get(
            "/v1alpha1/inferenceInstance", headers=tokens["alice"]
        )
        assert listed.status_code == 200, listed.text
        assert [i["id"] for i in listed.json()] == [str(bobs)]
        dashboards = oidc_client.get(
            f"{url}/dashboards", headers=tokens["alice"]
        )
        assert dashboards.status_code == 200, dashboards.text
        denied = oidc_client.delete(url, headers=tokens["alice"])
        assert denied.status_code == 403
        assert (
            denied.json()["detail"] == "You do not own this inference instance"
        )
    finally:
        delete_rows(DBInferenceInstance, bobs)


def test_model_adapters_are_scoped(oidc_client, tokens, other_org):
    from models.model_adapters import DBModelAdapters

    model_id = oidc_client.get(MODELS, headers=tokens["alice"]).json()[0]["id"]
    adapters = f"/v1alpha1/model/{model_id}/adapters"
    created = oidc_client.post(
        adapters,
        json={"name": "alices-adapter", "hf_id": "alice/adapter"},
        headers=tokens["alice"],
    )
    assert created.status_code == 201, created.text
    adapter_id = created.json()["id"]
    add_row(
        DBModelAdapters(
            name="other-adapter",
            model_id=uuid.UUID(model_id),
            hf_id="other/adapter",
            org_id=other_org,
        )
    )
    listed = oidc_client.get(adapters, headers=tokens["bob"])
    assert [a["name"] for a in listed.json()] == ["alices-adapter"]
    url = f"{adapters}/{adapter_id}"
    assert oidc_client.get(url, headers=tokens["bob"]).status_code == 200
    denied = oidc_client.put(
        url,
        json={"name": "renamed", "hf_id": "alice/adapter"},
        headers=tokens["bob"],
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "You do not own this model adapter"
    assert oidc_client.delete(url, headers=tokens["bob"]).status_code == 403
    assert oidc_client.delete(url, headers=tokens["carol"]).status_code == 204


def test_finetune_jobs_are_scoped(oidc_client, tokens, other_org):
    from models.finetune import DBFinetune

    model_id = oidc_client.get(MODELS, headers=tokens["alice"]).json()[0]["id"]
    finetunes = f"/v1alpha1/models/{model_id}/finetune"
    add_row(
        DBFinetune(
            name="other-job",
            model_id=uuid.UUID(model_id),
            params={},
            org_id=other_org,
        )
    )
    with mock.patch("api.finetune.finetune_controller") as controller:
        controller.submit_job = mock.AsyncMock()
        controller.get_job_status = mock.AsyncMock(return_value="Running")
        controller.delete_job = mock.AsyncMock()
        created = oidc_client.post(
            finetunes,
            json={"name": "alices-job", "params": {"epochs": 1}},
            headers=tokens["alice"],
        )
        assert created.status_code == 201, created.text
        url = f"{finetunes}/{created.json()['id']}"

        listed = oidc_client.get(finetunes, headers=tokens["bob"])
        assert listed.status_code == 200, listed.text
        assert [f["name"] for f in listed.json()] == ["alices-job"]
        assert oidc_client.get(url, headers=tokens["bob"]).status_code == 200
        denied = oidc_client.put(
            url, json={"name": "renamed"}, headers=tokens["bob"]
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "You do not own this finetune job"
        assert (
            oidc_client.delete(url, headers=tokens["bob"]).status_code == 403
        )
        controller.delete_job.assert_not_awaited()
        assert (
            oidc_client.delete(url, headers=tokens["alice"]).status_code == 204
        )
        controller.delete_job.assert_awaited_once()
