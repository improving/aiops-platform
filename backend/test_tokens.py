"""Personal API tokens (spec section 5.4). Tokens are resolved only after
the AUTH_MODE=disabled shortcut, so every test runs in oidc mode with the
test_auth fixtures and a signed JWT to create the tokens."""

import hashlib
import uuid
from datetime import datetime, timedelta

from auth.tokens import (
    PREFIX_LENGTH,
    SECRET_LENGTH,
    TOKEN_PREFIX,
    generate_token,
    hash_secret,
    split_token,
)
from db.database import get_db_direct
from models.api_token import ApiToken
from models.membership import Membership
from models.organization import DEFAULT_ORG_SLUG, Organization
from models.user import User
from testing.rows import NOTEBOOKS, notebook_payload
from testing.tokens import bearer, make_token

TOKENS = "/v1alpha1/tokens"
# The catalog list has no per-row Kubernetes check; /inferenceInstance and
# /notebooks ask the cluster for every row they list.
MODELS = "/v1alpha1/models"


def jwt_for(rsa_key, sub, roles=("member",)):  # noqa: F811
    return bearer(
        make_token(rsa_key, sub=sub, email=f"{sub}@example.test", roles=roles)
    )


def create_token(client, headers, **body):
    payload = {"name": "laptop", "scope": "write", **body}
    response = client.post(TOKENS, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def token_row(prefix: str) -> ApiToken:
    db = get_db_direct()
    try:
        return db.query(ApiToken).filter(ApiToken.prefix == prefix).one()
    finally:
        db.close()


def set_token(prefix: str, **fields):
    db = get_db_direct()
    try:
        row = db.query(ApiToken).filter(ApiToken.prefix == prefix).one()
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    finally:
        db.close()


# --- format -------------------------------------------------------------------


def test_generate_token_format():
    prefix, secret, full = generate_token()
    assert len(prefix) == PREFIX_LENGTH
    assert len(secret) == SECRET_LENGTH
    assert prefix.isalnum() and secret.isalnum()
    assert full == f"{TOKEN_PREFIX}{prefix}_{secret}"
    assert split_token(full) == (prefix, secret)
    assert split_token("aiops_short") is None
    assert split_token("Bearer nope") is None
    assert hash_secret(secret) == hashlib.sha256(secret.encode()).hexdigest()


# --- create and list ----------------------------------------------------------


def test_create_returns_the_token_once_and_stores_the_hash(
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
):
    alice = jwt_for(rsa_key, "tok-alice")
    body = create_token(oidc_client, alice, expires_in_days=10)
    assert body["token"].startswith(TOKEN_PREFIX)
    prefix, secret = split_token(body["token"])
    assert body["prefix"] == prefix
    assert body["scope"] == "write"
    assert body["name"] == "laptop"
    assert body["revoked_at"] is None
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=9) < expires - datetime.now() <= timedelta(days=10)

    row = token_row(prefix)
    assert row.token_hash == hash_secret(secret)
    assert secret not in (row.token_hash, row.prefix, row.name)

    listed = oidc_client.get(TOKENS, headers=alice).json()
    mine = [t for t in listed if t["prefix"] == prefix]
    assert len(mine) == 1
    assert "token" not in mine[0]


def test_create_retries_once_on_prefix_collision(
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
    monkeypatch,
):
    """A prefix collision at create is rare (spec: unique across every
    organization) but must not surface as a raw 500: one retry with a
    freshly generated prefix succeeds."""
    from auth.tokens import generate_token as real_generate_token

    alice = jwt_for(rsa_key, "tok-alice")
    colliding = create_token(oidc_client, alice)["prefix"]

    calls = []

    def flaky_generate_token():
        _, secret, _ = real_generate_token()
        if not calls:
            calls.append(1)
            return colliding, secret, f"{TOKEN_PREFIX}{colliding}_{secret}"
        calls.append(2)
        return real_generate_token()

    monkeypatch.setattr("auth.tokens.generate_token", flaky_generate_token)
    body = create_token(oidc_client, alice)
    assert body["prefix"] != colliding
    assert calls == [1, 2]


def test_create_answers_500_when_every_retry_collides(
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
    monkeypatch,
):
    alice = jwt_for(rsa_key, "tok-alice")
    colliding = create_token(oidc_client, alice)["prefix"]

    def always_collides():
        secret = "b" * SECRET_LENGTH
        return colliding, secret, f"{TOKEN_PREFIX}{colliding}_{secret}"

    monkeypatch.setattr("auth.tokens.generate_token", always_collides)
    response = oidc_client.post(
        TOKENS, json={"name": "x", "scope": "read"}, headers=alice
    )
    assert response.status_code == 500


def test_expires_in_days_bounds_and_default(oidc_client, rsa_key):  # noqa: F811
    alice = jwt_for(rsa_key, "tok-alice")
    default = create_token(oidc_client, alice)
    expires = datetime.fromisoformat(default["expires_at"])
    assert timedelta(days=89) < expires - datetime.now() <= timedelta(days=90)
    for days in (0, 366):
        response = oidc_client.post(
            TOKENS,
            json={"name": "x", "scope": "read", "expires_in_days": days},
            headers=alice,
        )
        assert response.status_code == 422
    assert (
        oidc_client.post(
            TOKENS, json={"name": "x", "scope": "admin"}, headers=alice
        ).status_code
        == 422
    )


# --- resolution -----------------------------------------------------------------


def test_token_lists_the_catalog_as_its_user(oidc_client, rsa_key):  # noqa: F811
    alice = jwt_for(rsa_key, "tok-alice")
    token = create_token(oidc_client, alice)["token"]
    response = oidc_client.get(MODELS, headers=bearer(token))
    assert response.status_code == 200, response.text
    prefix, _ = split_token(token)
    assert token_row(prefix).last_used_at is not None


def test_read_token_is_a_viewer_and_write_token_keeps_the_role(
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
    notebook_controller,  # noqa: F811
):
    """POST /notebooks is require_writer (POST /models is require_admin,
    which would refuse a member's write token too)."""
    alice = jwt_for(rsa_key, "tok-alice")
    read = create_token(oidc_client, alice, scope="read")["token"]
    write = create_token(oidc_client, alice, scope="write")["token"]
    refused = oidc_client.post(
        NOTEBOOKS, json=notebook_payload("tok-read"), headers=bearer(read)
    )
    assert refused.status_code == 403
    assert oidc_client.get(MODELS, headers=bearer(read)).status_code == 200
    created = oidc_client.post(
        NOTEBOOKS, json=notebook_payload("tok-write"), headers=bearer(write)
    )
    assert created.status_code == 200, created.text
    deleted = oidc_client.delete(
        f"{NOTEBOOKS}/{created.json()['id']}", headers=bearer(write)
    )
    assert deleted.status_code == 200, deleted.text


def test_mcp_token_is_valid_on_the_mcp_endpoint_only(
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
    monkeypatch,
):
    """What an IDE or a Langflow flow holds: it reaches the tools with
    the member's own role and nothing else of the API."""
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    alice = jwt_for(rsa_key, "tok-alice")
    token = create_token(oidc_client, alice, scope="mcp")["token"]
    refused = oidc_client.get(MODELS, headers=bearer(token))
    assert refused.status_code == 403
    assert "/v1alpha1/mcp" in refused.json()["detail"]
    assert (
        oidc_client.get(
            "/v1alpha1/mcp/servers", headers=bearer(token)
        ).status_code
        == 403
    )
    listed = oidc_client.post(
        "/v1alpha1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=bearer(token),
    )
    assert listed.status_code == 200, listed.text
    tools = listed.json()["result"]["tools"]
    assert all(t["name"].endswith("echo") for t in tools)


def test_a_managed_token_is_kept_renewed_and_never_piles_up(
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
):
    from auth.tokens import ensure_managed_token

    alice = jwt_for(rsa_key, "tok-managed")
    oidc_client.get(MODELS, headers=alice)
    db = get_db_direct()
    try:
        user = db.query(User).filter(User.sub == "tok-managed").one()
        member = (
            db.query(Membership).filter(Membership.user_id == user.id).one()
        )
        args = dict(
            user_id=user.id, org_id=member.org_id, name="langflow", scope="mcp"
        )

        def rows():
            return (
                db.query(ApiToken)
                .filter(
                    ApiToken.user_id == user.id, ApiToken.name == "langflow"
                )
                .all()
            )

        first = ensure_managed_token(db, holder_has_it=False, **args)
        assert first.startswith("aiops_") and len(rows()) == 1
        # The holder has it and it is far from its end: nothing to do.
        assert ensure_managed_token(db, holder_has_it=True, **args) is None
        # The holder lost it: a new one, and the old row is gone.
        second = ensure_managed_token(db, holder_has_it=False, **args)
        assert second != first and len(rows()) == 1
        # Near its end: renewed although the holder has it.
        rows()[0].expires_at = datetime.now() + timedelta(days=5)
        db.commit()
        third = ensure_managed_token(db, holder_has_it=True, **args)
        assert third is not None and len(rows()) == 1
        listed = oidc_client.post(
            "/v1alpha1/mcp", json={}, headers=bearer(second)
        )
        assert listed.status_code == 401

        # The holder keeps one token, whatever the organization: after a
        # provision in another organization it holds that one, so back
        # here a new one is due although "the holder has it".
        other = Organization(name="Managed other", slug="managed-other")
        db.add(other)
        db.commit()
        elsewhere = dict(args, org_id=other.id)
        assert ensure_managed_token(db, holder_has_it=True, **elsewhere)
        assert ensure_managed_token(db, holder_has_it=True, **args) is not None
        assert ensure_managed_token(db, holder_has_it=True, **args) is None
    finally:
        for row in rows():
            db.delete(row)
        db.query(Organization).filter(
            Organization.slug == "managed-other"
        ).delete()
        db.commit()
        db.close()


def test_revoked_token_is_401(oidc_client, rsa_key):  # noqa: F811
    alice = jwt_for(rsa_key, "tok-alice")
    body = create_token(oidc_client, alice)
    assert (
        oidc_client.delete(f"{TOKENS}/{body['id']}", headers=alice).status_code
        == 204
    )
    response = oidc_client.get(MODELS, headers=bearer(body["token"]))
    assert response.status_code == 401
    assert response.json()["detail"] == "The token was revoked"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_expired_token_is_401(oidc_client, rsa_key):  # noqa: F811
    alice = jwt_for(rsa_key, "tok-alice")
    body = create_token(oidc_client, alice)
    set_token(body["prefix"], expires_at=datetime.now() - timedelta(minutes=1))
    response = oidc_client.get(MODELS, headers=bearer(body["token"]))
    assert response.status_code == 401
    assert response.json()["detail"] == "The token has expired"


def test_unknown_or_wrong_secret_is_401(oidc_client, rsa_key):  # noqa: F811
    alice = jwt_for(rsa_key, "tok-alice")
    body = create_token(oidc_client, alice)
    wrong = f"{TOKEN_PREFIX}{body['prefix']}_{'x' * SECRET_LENGTH}"
    assert oidc_client.get(MODELS, headers=bearer(wrong)).status_code == 401
    unknown = f"{TOKEN_PREFIX}{'z' * PREFIX_LENGTH}_{'x' * SECRET_LENGTH}"
    assert oidc_client.get(MODELS, headers=bearer(unknown)).status_code == 401


def test_token_cannot_manage_tokens(oidc_client, rsa_key):  # noqa: F811
    alice = jwt_for(rsa_key, "tok-alice")
    body = create_token(oidc_client, alice)
    headers = bearer(body["token"])
    for call in (
        lambda: oidc_client.get(TOKENS, headers=headers),
        lambda: oidc_client.post(
            TOKENS, json={"name": "x", "scope": "read"}, headers=headers
        ),
        lambda: oidc_client.delete(f"{TOKENS}/{body['id']}", headers=headers),
    ):
        response = call()
        assert response.status_code == 403
        assert response.json()["detail"] == "A token cannot manage tokens"


def test_service_account_cannot_manage_tokens(oidc_client, rsa_key):  # noqa: F811
    """A client-credentials token (no email, azp set) is a service
    identity: it gets a clearer message than the personal-token case,
    which is fixed verbatim above."""
    service = bearer(
        make_token(rsa_key, sub="svc-sub", email=None, azp="svc-client")
    )
    for call in (
        lambda: oidc_client.get(TOKENS, headers=service),
        lambda: oidc_client.post(
            TOKENS, json={"name": "x", "scope": "read"}, headers=service
        ),
    ):
        response = call()
        assert response.status_code == 403
        assert (
            response.json()["detail"]
            == "Only a signed-in user can manage tokens"
        )


def test_token_use_refreshes_last_seen_at(oidc_client, rsa_key):  # noqa: F811
    from auth.current_user import LAST_SEEN_RESOLUTION

    alice = jwt_for(rsa_key, "tok-alice")
    body = create_token(oidc_client, alice)
    stale = datetime.now() - LAST_SEEN_RESOLUTION - timedelta(minutes=1)
    db = get_db_direct()
    try:
        user = db.query(User).filter(User.sub == "tok-alice").one()
        user.last_seen_at = stale
        db.commit()
    finally:
        db.close()

    response = oidc_client.get(MODELS, headers=bearer(body["token"]))
    assert response.status_code == 200, response.text

    db = get_db_direct()
    try:
        user = db.query(User).filter(User.sub == "tok-alice").one()
        assert user.last_seen_at > stale
    finally:
        db.close()


def test_token_whose_membership_is_gone_is_401(oidc_client, rsa_key):  # noqa: F811
    gone = jwt_for(rsa_key, "tok-gone")
    body = create_token(oidc_client, gone)
    db = get_db_direct()
    try:
        user = db.query(User).filter(User.sub == "tok-gone").one()
        org = (
            db.query(Organization)
            .filter(Organization.slug == DEFAULT_ORG_SLUG)
            .one()
        )
        db.query(Membership).filter(
            Membership.user_id == user.id, Membership.org_id == org.id
        ).delete()
        db.commit()
    finally:
        db.close()
    response = oidc_client.get(MODELS, headers=bearer(body["token"]))
    assert response.status_code == 401
    assert (
        response.json()["detail"]
        == "The token's organization membership is gone"
    )


# --- admin view -----------------------------------------------------------------


def test_admin_sees_every_token_with_all_and_may_revoke(oidc_client, rsa_key):  # noqa: F811
    alice = jwt_for(rsa_key, "tok-alice")
    carol = jwt_for(rsa_key, "tok-carol", roles=("admin",))
    body = create_token(oidc_client, alice)
    assert (
        oidc_client.get(
            TOKENS, params={"all": "true"}, headers=alice
        ).status_code
        == 403
    )
    everyone = oidc_client.get(
        TOKENS, params={"all": "true"}, headers=carol
    ).json()
    assert any(t["id"] == body["id"] for t in everyone)
    only_mine = oidc_client.get(TOKENS, headers=carol).json()
    assert not any(t["id"] == body["id"] for t in only_mine)
    # A member cannot revoke someone else's token: it is not found.
    bob = jwt_for(rsa_key, "tok-bob")
    assert (
        oidc_client.delete(f"{TOKENS}/{body['id']}", headers=bob).status_code
        == 404
    )
    assert (
        oidc_client.delete(f"{TOKENS}/{body['id']}", headers=carol).status_code
        == 204
    )
    assert token_row(body["prefix"]).revoked_at is not None
    assert (
        oidc_client.delete(
            f"{TOKENS}/{uuid.uuid4()}", headers=carol
        ).status_code
        == 404
    )
