"""Pytest defaults and the shared fixtures of the backend.

``TEST_MODE`` has to be set before ``utils.genid`` is imported (ids are
deterministic only then), and ``AUTH_MODE=disabled`` lets the tests call
the API without a token. ``hack/runtest.sh`` exports both as well; this
keeps single-test commands working. The imports below come after the
defaults on purpose (E402), since they pull ``utils.genid`` in.

Plain helpers (token signing, direct row access, fake pods) live in the
``testing`` package; no test module imports another test module.
"""

import os

os.environ.setdefault("TEST_MODE", "true")
os.environ.setdefault("AUTH_MODE", "disabled")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from jwt import PyJWKClient  # noqa: E402
from jwt.algorithms import RSAAlgorithm  # noqa: E402

from auth import jwt as auth_jwt  # noqa: E402
from core import create_app  # noqa: E402
from db.database import get_db_direct  # noqa: E402
from models.organization import Organization  # noqa: E402
from testing.rows import NOT_READY  # noqa: E402
from testing.tokens import ISSUER, KID, bearer, make_token  # noqa: E402


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


@pytest.fixture
def tokens(rsa_key):
    return {
        "alice": bearer(make_token(rsa_key, sub="alice", roles=("member",))),
        "bob": bearer(make_token(rsa_key, sub="bob", roles=("member",))),
        "carol": bearer(make_token(rsa_key, sub="carol", roles=("admin",))),
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
def other_org():
    """The seeded second organization; rows added to it are removed afterwards."""
    from auth.dev_users import OTHER_ORG_SLUG, ensure_dev_organizations
    from models.finetune import DBFinetune
    from models.inference_instance import DBInferenceInstance
    from models.model_adapters import DBModelAdapters
    from models.notebook import Notebook
    from models.vectordb_instance import DBVectorDBInstance

    db = get_db_direct()
    ensure_dev_organizations(db)
    org = (
        db.query(Organization)
        .filter(Organization.slug == OTHER_ORG_SLUG)
        .one()
    )
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
    db.commit()
    db.close()
