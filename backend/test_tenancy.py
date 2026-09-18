"""Tenancy: dev identities, the active organization, memberships,
invitations (spec section 5.1, 5.2, 5.6)."""

import uuid
from datetime import datetime

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Query

from auth.current_user import CurrentUser, get_current_user
from auth.dev_users import (
    DEV_USERS,
    OTHER_ORG_SLUG,
    ensure_dev_memberships,
    ensure_dev_organizations,
)
from core import create_app
from db.database import get_db_direct
from models.invitation import Invitation
from models.membership import Membership
from models.notebook import Notebook
from models.organization import Organization
from models.user import User

STATE_ROUTE = "/test/state"
NOTEBOOKS = "/v1alpha1/notebooks"


def _add_state_route(app):
    """A route that echoes what get_current_user stored on the request."""
    if any(getattr(r, "path", None) == STATE_ROUTE for r in app.routes):
        return

    @app.get(STATE_ROUTE)
    def state(request: Request, user: CurrentUser = Depends(get_current_user)):
        current = request.state.current_user
        return {
            "sub": current.sub,
            "org_slug": current.org_slug,
            "role": current.role,
            "is_platform_admin": current.is_platform_admin,
            "auth_kind": current.auth_kind,
            "same_object": current is user,
        }


@pytest.fixture
def client():
    app = create_app()
    _add_state_route(app)
    with TestClient(app) as c:
        yield c


def dev(name: str) -> dict[str, str]:
    return {"X-Dev-User": name}


def org_by_slug(slug: str) -> Organization | None:
    db = get_db_direct()
    try:
        return db.query(Organization).filter(Organization.slug == slug).first()
    finally:
        db.close()


def user_by_sub(sub: str) -> User | None:
    db = get_db_direct()
    try:
        return db.query(User).filter(User.sub == sub).first()
    finally:
        db.close()


def memberships_of(sub: str) -> dict[str, str]:
    """{org slug: role} for the user."""
    db = get_db_direct()
    try:
        rows = (
            db.query(Membership, Organization)
            .join(Organization, Organization.id == Membership.org_id)
            .join(User, User.id == Membership.user_id)
            .filter(User.sub == sub)
            .all()
        )
        return {org.slug: membership.role for membership, org in rows}
    finally:
        db.close()


# --- Task 1: dev identities and request state --------------------------------


def test_default_dev_identity_is_the_dev_admin(client):
    body = client.get(STATE_ROUTE).json()
    assert body["sub"] == "dev"
    assert body["role"] == "admin"
    assert body["is_platform_admin"] is True
    assert body["auth_kind"] == "dev"
    assert body["same_object"] is True


def test_x_dev_user_picks_a_fixed_identity(client):
    body = client.get(STATE_ROUTE, headers=dev("alice")).json()
    assert body["sub"] == "dev:alice"
    assert body["auth_kind"] == "dev"
    user = user_by_sub("dev:alice")
    assert user is not None
    assert user.email == "alice@example.test"


def test_unknown_dev_user_is_401(client):
    response = client.get(STATE_ROUTE, headers=dev("mallory"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Unknown dev user 'mallory'"


def test_organization_other_is_seeded_on_first_dev_request(client):
    assert client.get(STATE_ROUTE).status_code == 200
    other = org_by_slug("other")
    assert other is not None
    assert other.name == "Other"


def test_request_id_is_generated_and_returned(client):
    response = client.get("/health")
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_request_id_is_echoed_when_sent(client):
    response = client.get("/health", headers={"X-Request-ID": "req-123"})
    assert response.headers["X-Request-ID"] == "req-123"


# --- Fix round 1: the dev seeds are race-safe --------------------------------


def _fake_missing_once(monkeypatch):
    """Make the next ``Query.first()`` call lie that a row is missing.

    Simulates two concurrent first dev requests both passing the "exists"
    check: the row is actually already there (committed by the "winner"
    before this call), but the check under test is made to miss it once,
    so the insert path below runs into the unique constraint for real.
    """
    real_first = Query.first
    state = {"faked": False}

    def first_once(self):
        if not state["faked"]:
            state["faked"] = True
            return None
        return real_first(self)

    monkeypatch.setattr(Query, "first", first_once)


def test_ensure_dev_organizations_recovers_from_a_concurrent_insert(
    monkeypatch,
):
    """Two concurrent first dev requests can both pass the "exists" check;
    the loser must recover instead of raising IntegrityError (spec 5.6)."""
    setup_db = get_db_direct()
    try:
        ensure_dev_organizations(setup_db)  # the org already exists for real
    finally:
        setup_db.close()

    db = get_db_direct()
    try:
        _fake_missing_once(monkeypatch)

        ensure_dev_organizations(db)  # must not raise

        orgs = (
            db.query(Organization)
            .filter(Organization.slug == OTHER_ORG_SLUG)
            .all()
        )
        assert len(orgs) == 1
    finally:
        db.close()


def test_ensure_dev_memberships_recovers_from_a_concurrent_insert(
    monkeypatch,
):
    """Two concurrent first dev requests can both pass the "exists" check;
    the loser must recover instead of raising IntegrityError (spec 5.6)."""
    setup_db = get_db_direct()
    try:
        user = setup_db.query(User).filter(User.sub == "dev:bob").first()
        if user is None:
            user = User(sub="dev:bob", email="bob@example.test", name="Bob")
            setup_db.add(user)
            setup_db.flush()
        ensure_dev_organizations(setup_db)
        ensure_dev_memberships(setup_db, user, DEV_USERS["bob"])
        setup_db.commit()
        user_id = user.id
    finally:
        setup_db.close()

    db = get_db_direct()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        _fake_missing_once(monkeypatch)

        ensure_dev_memberships(db, user, DEV_USERS["bob"])  # must not raise

        memberships = (
            db.query(Membership).filter(Membership.user_id == user_id).all()
        )
        assert len(memberships) == 1
    finally:
        db.close()


NOT_A_MEMBER = "You are not a member of this organization"

# Fixed ids so the per-column genid counters (and the snapshot ids) stay put.
ALICE_NB_ID = uuid.UUID("7e5a0c00-0000-4000-8000-00000000a11c")
OUTSIDER_NB_ID = uuid.UUID("7e5a0c00-0000-4000-8000-0000000000e1")


def _add(row):
    db = get_db_direct()
    try:
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _delete(model, *ids):
    db = get_db_direct()
    try:
        db.query(model).filter(model.id.in_(ids)).delete()
        db.commit()
    finally:
        db.close()


# --- Task 2: the active organization ----------------------------------------


def test_dev_users_land_in_their_first_membership(client):
    assert (
        client.get(STATE_ROUTE, headers=dev("outsider")).json()["org_slug"]
        == "other"
    )
    assert (
        client.get(STATE_ROUTE, headers=dev("alice")).json()["org_slug"]
        == "default"
    )
    assert memberships_of("dev:outsider") == {"other": "member"}
    assert memberships_of("dev:alice") == {"default": "member"}


def test_x_org_switches_a_member_between_organizations(client):
    body = client.get(STATE_ROUTE, headers={**dev("dev"), "X-Org": "other"})
    assert body.status_code == 200
    assert body.json()["org_slug"] == "other"
    assert body.json()["role"] == "admin"


def test_x_org_without_membership_is_403(client):
    response = client.get(
        STATE_ROUTE, headers={**dev("alice"), "X-Org": "other"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == NOT_A_MEMBER


def test_x_org_unknown_slug_is_403(client):
    response = client.get(
        STATE_ROUTE, headers={**dev("dev"), "X-Org": "nowhere"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == NOT_A_MEMBER


def test_lists_are_scoped_to_the_active_organization(
    client,
    notebook_controller,  # noqa: F811
):
    # notebook_controller (test_auth.py) mocks NotebooksController and the
    # pod check: the list and get routes ask Kubernetes for every row.
    # user rows exist after the first request as that identity
    assert client.get(STATE_ROUTE, headers=dev("alice")).status_code == 200
    assert client.get(STATE_ROUTE, headers=dev("outsider")).status_code == 200
    default_org = org_by_slug("default")
    other = org_by_slug("other")
    _add(
        Notebook(
            id=ALICE_NB_ID,
            name="alices-nb",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
            org_id=default_org.id,
            owner_id=user_by_sub("dev:alice").id,
        )
    )
    _add(
        Notebook(
            id=OUTSIDER_NB_ID,
            name="outsiders-nb",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
            org_id=other.id,
            owner_id=user_by_sub("dev:outsider").id,
        )
    )
    try:
        alice_sees = {
            n["name"]
            for n in client.get(NOTEBOOKS, headers=dev("alice")).json()
        }
        outsider_sees = {
            n["name"]
            for n in client.get(NOTEBOOKS, headers=dev("outsider")).json()
        }
        assert "alices-nb" in alice_sees
        assert "outsiders-nb" not in alice_sees
        assert "outsiders-nb" in outsider_sees
        assert "alices-nb" not in outsider_sees
        # The row itself answers 403 across the boundary.
        response = client.get(
            f"{NOTEBOOKS}/{ALICE_NB_ID}", headers=dev("outsider")
        )
        assert response.status_code == 403
    finally:
        _delete(Notebook, ALICE_NB_ID, OUTSIDER_NB_ID)


def test_pending_invitation_is_accepted_at_next_resolve(client):
    assert client.get(STATE_ROUTE, headers=dev("bob")).status_code == 200
    other = org_by_slug("other")
    invitation_id = _add(
        Invitation(
            org_id=other.id,
            email="BOB@example.test",  # matched case-insensitively
            role="viewer",
            created_at=datetime.now(),
        )
    )
    body = client.get(STATE_ROUTE, headers=dev("bob")).json()
    # The first membership (default) stays the active one.
    assert body["org_slug"] == "default"
    assert memberships_of("dev:bob") == {
        "default": "member",
        "other": "viewer",
    }
    db = get_db_direct()
    try:
        invitation = db.get(Invitation, invitation_id)
        assert invitation.accepted_at is not None
        assert invitation.accepted_user_id == user_by_sub("dev:bob").id
    finally:
        db.close()
    switched = client.get(
        STATE_ROUTE, headers={**dev("bob"), "X-Org": "other"}
    ).json()
    assert switched["org_slug"] == "other"
    assert switched["role"] == "viewer"


def test_invitation_for_an_existing_member_is_marked_accepted(client):
    assert client.get(STATE_ROUTE, headers=dev("alice")).status_code == 200
    default_org = org_by_slug("default")
    invitation_id = _add(
        Invitation(
            org_id=default_org.id,
            email="alice@example.test",
            role="admin",
            created_at=datetime.now(),
        )
    )
    assert client.get(STATE_ROUTE, headers=dev("alice")).status_code == 200
    # The membership keeps its role; the invitation is closed.
    assert memberships_of("dev:alice")["default"] == "member"
    db = get_db_direct()
    try:
        assert db.get(Invitation, invitation_id).accepted_at is not None
    finally:
        db.close()


ORGS = "/v1alpha1/organizations"
CURRENT = f"{ORGS}/current"


# --- Task 3: organizations API --------------------------------------------


def test_my_organizations_and_active(client):
    body = client.get(ORGS, headers=dev("dev")).json()
    slugs = {o["slug"]: o["role"] for o in body["organizations"]}
    assert slugs["default"] == "admin"
    assert slugs["other"] == "admin"
    assert body["active"] == "default"
    switched = client.get(ORGS, headers={**dev("dev"), "X-Org": "other"})
    assert switched.json()["active"] == "other"
    outsider = client.get(ORGS, headers=dev("outsider")).json()
    assert [o["slug"] for o in outsider["organizations"]] == ["other"]


def test_current_organization_document(client):
    body = client.get(CURRENT, headers=dev("alice")).json()
    assert body["slug"] == "default"
    assert body["name"]
    assert body["role"] == "member"
    assert body["is_platform_admin"] is False
    assert body["member_count"] >= 2
    assert "budget_usd" in body
    assert client.get(CURRENT, headers=dev("dev")).json()["is_platform_admin"]


def test_platform_admin_creates_an_organization_and_is_its_admin(client):
    response = client.post(
        ORGS, json={"slug": "acme", "name": "Acme"}, headers=dev("dev")
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "admin"
    assert memberships_of("dev")["acme"] == "admin"
    again = client.post(
        ORGS, json={"slug": "acme", "name": "Acme"}, headers=dev("dev")
    )
    assert again.status_code == 409
    assert (
        again.json()["detail"]
        == "An organization with slug 'acme' already exists"
    )


def test_member_cannot_create_an_organization(client):
    response = client.post(
        ORGS, json={"slug": "nope", "name": "Nope"}, headers=dev("alice")
    )
    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "This action needs the platform admin role"
    )


@pytest.mark.parametrize("slug", ["A", "-bad", "bad-", "x" * 41, "has space"])
def test_slug_rule(client, slug):
    response = client.post(
        ORGS, json={"slug": slug, "name": "x"}, headers=dev("dev")
    )
    assert response.status_code == 422


def test_members_are_admin_only(client):
    assert client.get(STATE_ROUTE, headers=dev("alice")).status_code == 200
    denied = client.get(f"{CURRENT}/members", headers=dev("alice"))
    assert denied.status_code == 403
    rows = client.get(f"{CURRENT}/members", headers=dev("dev")).json()
    emails = {r["email"]: r for r in rows}
    assert emails["alice@example.test"]["role"] == "member"
    assert emails["alice@example.test"]["created_at"]


def test_change_role_and_last_admin_rule(client):
    assert client.get(STATE_ROUTE, headers=dev("bob")).status_code == 200
    bob_id = str(user_by_sub("dev:bob").id)
    response = client.put(
        f"{CURRENT}/members/{bob_id}",
        json={"role": "admin"},
        headers=dev("dev"),
    )
    assert response.status_code == 200, response.text
    assert memberships_of("dev:bob")["default"] == "admin"
    # Back to member; the dev admin still holds the org.
    assert (
        client.put(
            f"{CURRENT}/members/{bob_id}",
            json={"role": "member"},
            headers=dev("dev"),
        ).status_code
        == 200
    )
    bad_role = client.put(
        f"{CURRENT}/members/{bob_id}",
        json={"role": "owner"},
        headers=dev("dev"),
    )
    assert bad_role.status_code == 422
    # In "acme" the platform admin is the only admin (created here too, so
    # the test does not depend on the order pytest runs the module in).
    assert client.post(
        ORGS, json={"slug": "acme", "name": "Acme"}, headers=dev("dev")
    ).status_code in (201, 409)
    dev_id = str(user_by_sub("dev").id)
    demote = client.put(
        f"{CURRENT}/members/{dev_id}",
        json={"role": "member"},
        headers={**dev("dev"), "X-Org": "acme"},
    )
    assert demote.status_code == 409
    assert (
        demote.json()["detail"] == "The organization needs at least one admin"
    )


def test_remove_member_rules(client):
    dev_id = str(user_by_sub("dev").id)
    self_removal = client.delete(
        f"{CURRENT}/members/{dev_id}", headers=dev("dev")
    )
    assert self_removal.status_code == 409
    assert self_removal.json()["detail"] == "You cannot remove yourself"
    assert client.get(STATE_ROUTE, headers=dev("viewer")).status_code == 200
    viewer_id = str(user_by_sub("dev:viewer").id)
    removed = client.delete(
        f"{CURRENT}/members/{viewer_id}", headers=dev("dev")
    )
    assert removed.status_code == 204
    assert "default" not in memberships_of("dev:viewer")
    # The dev seed puts the viewer back on the next request.
    assert client.get(STATE_ROUTE, headers=dev("viewer")).status_code == 200
    assert memberships_of("dev:viewer") == {"default": "viewer"}
    missing = client.delete(
        f"{CURRENT}/members/{uuid.uuid4()}", headers=dev("dev")
    )
    assert missing.status_code == 404


def test_remove_member_rotates_the_litellm_key(client, monkeypatch):
    # The organization's key sits in every member's Langflow account, so
    # removal rotates it first, and a rotation that fails keeps the
    # member: the key is what the removal actually revokes.
    from utils.litellm import LiteLLMError

    rotated = []
    monkeypatch.setattr(
        "api.organizations.rotate_org_key",
        lambda db, org: rotated.append(org.slug),
    )
    viewer_id = str(user_by_sub("dev:viewer").id)
    removed = client.delete(
        f"{CURRENT}/members/{viewer_id}", headers=dev("dev")
    )
    assert removed.status_code == 204
    assert rotated == ["default"]

    def failing(db, org):
        raise LiteLLMError("LiteLLM unreachable: refused")

    monkeypatch.setattr("api.organizations.rotate_org_key", failing)
    # The dev seed has put the viewer back by now.
    client.get(STATE_ROUTE, headers=dev("viewer"))
    kept = client.delete(f"{CURRENT}/members/{viewer_id}", headers=dev("dev"))
    assert kept.status_code == 502
    assert "could not be rotated" in kept.json()["detail"]
    assert memberships_of("dev:viewer") == {"default": "viewer"}


def test_remove_member_revokes_their_own_litellm_key(client, monkeypatch):
    # The member's own key (their Langflow account, ensure_user_key) is
    # revoked with the removal, and a revocation that fails keeps the
    # member, like the rotation: a key that still works is access.
    from utils.litellm import LiteLLMError

    monkeypatch.setattr("api.organizations.rotate_org_key", lambda db, o: None)
    revoked = []
    monkeypatch.setattr(
        "api.organizations.delete_user_key",
        lambda org, user_id: revoked.append((org.slug, str(user_id))),
    )
    viewer_id = str(user_by_sub("dev:viewer").id)
    removed = client.delete(
        f"{CURRENT}/members/{viewer_id}", headers=dev("dev")
    )
    assert removed.status_code == 204
    assert revoked == [("default", viewer_id)]

    def failing(org, user_id):
        raise LiteLLMError("LiteLLM unreachable: refused")

    monkeypatch.setattr("api.organizations.delete_user_key", failing)
    client.get(STATE_ROUTE, headers=dev("viewer"))
    kept = client.delete(f"{CURRENT}/members/{viewer_id}", headers=dev("dev"))
    assert kept.status_code == 502
    assert "could not be revoked" in kept.json()["detail"]
    assert memberships_of("dev:viewer") == {"default": "viewer"}


def test_invitation_lifecycle(client):
    created = client.post(
        f"{CURRENT}/invitations",
        json={"email": "Dana@Example.test", "role": "member"},
        headers=dev("dev"),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "dana@example.test"
    assert body["accepted_at"] is None
    refreshed = client.post(
        f"{CURRENT}/invitations",
        json={"email": "dana@example.test", "role": "viewer"},
        headers=dev("dev"),
    )
    assert refreshed.status_code == 201
    assert refreshed.json()["id"] == body["id"]
    assert refreshed.json()["role"] == "viewer"
    listed = client.get(f"{CURRENT}/invitations", headers=dev("dev")).json()
    assert any(i["id"] == body["id"] for i in listed)
    assert (
        client.get(f"{CURRENT}/invitations", headers=dev("alice")).status_code
        == 403
    )
    existing = client.post(
        f"{CURRENT}/invitations",
        json={"email": "alice@example.test", "role": "member"},
        headers=dev("dev"),
    )
    assert existing.status_code == 409
    assert (
        existing.json()["detail"] == "alice@example.test is already a member"
    )
    withdrawn = client.delete(
        f"{CURRENT}/invitations/{body['id']}", headers=dev("dev")
    )
    assert withdrawn.status_code == 204
    assert (
        client.delete(
            f"{CURRENT}/invitations/{body['id']}", headers=dev("dev")
        ).status_code
        == 404
    )
