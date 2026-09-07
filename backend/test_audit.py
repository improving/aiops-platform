"""The request id and the audit trail (spec section 5.3)."""

import uuid
from datetime import datetime, timedelta
from unittest import mock

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from starlette.responses import Response

from audit import events
from auth.current_user import CurrentUser, get_current_user
from core import create_app
from db.database import get_db_direct
from models.audit_event import AuditEvent
from models.organization import Organization
from models.user import User
from models.vectordb_instance import DBVectorDBInstance
from models.workload_credential import WorkloadCredential

AUDIT = "/v1alpha1/organizations/current/audit"
INVITATIONS = "/v1alpha1/organizations/current/invitations"
# Under /v1alpha1/ so the middleware records it (kind "test").
BOOM_ROUTE = "/v1alpha1/test/boom"
# Sends http.response.start, then raises: simulates a broken streamed
# answer, where the response already started before the app failed.
BOOM_STARTED_ROUTE = "/v1alpha1/test/boom-started"

# Fixed ids: no genid counter is consumed, so snapshot ids do not shift.
VDB_ID = uuid.UUID("a0d17000-0000-4000-8000-00000000abcd")


def _add_boom_route(app):
    if any(getattr(r, "path", None) == BOOM_ROUTE for r in app.routes):
        return

    @app.post(BOOM_ROUTE)
    def boom(user: CurrentUser = Depends(get_current_user)):
        raise RuntimeError("boom")


class _StartsThenBreaks(Response):
    """Sends http.response.start, then raises before the body: a
    response that has already started when the app fails."""

    def __init__(self):
        super().__init__(status_code=200)

    async def __call__(self, scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        raise RuntimeError("boom-after-start")


def _add_boom_started_route(app):
    if any(getattr(r, "path", None) == BOOM_STARTED_ROUTE for r in app.routes):
        return

    @app.post(BOOM_STARTED_ROUTE)
    def boom_started(user: CurrentUser = Depends(get_current_user)):
        return _StartsThenBreaks()


@pytest.fixture
def client():
    app = create_app()
    _add_boom_route(app)
    _add_boom_started_route(app)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def lenient_client():
    """Lets an unhandled exception become a 500 instead of re-raising."""
    app = create_app()
    _add_boom_route(app)
    _add_boom_started_route(app)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def dev(name: str) -> dict[str, str]:
    return {"X-Dev-User": name}


def events_for(request_id: str) -> list[AuditEvent]:
    db = get_db_direct()
    try:
        return (
            db.query(AuditEvent)
            .filter(AuditEvent.request_id == request_id)
            .all()
        )
    finally:
        db.close()


def default_org_id():
    db = get_db_direct()
    try:
        return (
            db.query(Organization)
            .filter(Organization.slug == "default")
            .one()
            .id
        )
    finally:
        db.close()


# --- path parsing -------------------------------------------------------------


def test_parse_path_kind_and_id():
    rid = "c0ffee00-0000-4000-8000-00000000ef01"
    assert events.parse_path(f"/v1alpha1/inferenceInstance/{rid}/restart") == (
        "inferenceInstance",
        rid,
    )
    assert events.parse_path(
        "/v1alpha1/organizations/current/invitations/" + rid
    ) == ("organizations", rid)
    assert events.parse_path("/v1alpha1/tokens") == ("tokens", None)
    assert events.parse_path("/health") is None


def test_action_for_method_and_verb():
    rid = "c0ffee00-0000-4000-8000-00000000ef01"
    assert events.action_for("POST", "/v1alpha1/notebooks") == "create"
    assert events.action_for("PUT", "/v1alpha1/x") == "update"
    assert events.action_for("PATCH", "/v1alpha1/x") == "update"
    assert events.action_for("DELETE", "/v1alpha1/x") == "delete"
    for verb in ("restart", "stop", "resume", "scale"):
        path = f"/v1alpha1/inferenceInstance/{rid}/{verb}"
        assert events.action_for("POST", path) == verb


def test_should_record_excludes_reads_and_high_volume_routes():
    assert events.should_record("POST", "/v1alpha1/notebooks")
    assert not events.should_record("GET", "/v1alpha1/notebooks")
    assert not events.should_record("HEAD", "/v1alpha1/notebooks")
    assert not events.should_record("OPTIONS", "/v1alpha1/notebooks")
    assert not events.should_record("POST", "/v1alpha1/chat/completions")
    assert not events.should_record("POST", "/v1alpha1/embeddings")
    assert not events.should_record("POST", "/v1alpha1/rerank")
    assert not events.should_record("POST", "/v1alpha1/authz/route/api/x")
    assert not events.should_record("POST", "/reload-data")


# --- the middleware -----------------------------------------------------------


def test_post_records_one_event_with_kind_id_and_outcome(client):
    created = client.post(
        INVITATIONS,
        json={"email": "audited@example.test", "role": "member"},
        headers=dev("dev"),
    )
    assert created.status_code == 201, created.text
    request_id = created.headers["X-Request-ID"]
    (event,) = events_for(request_id)
    assert event.action == "create"
    assert event.resource_kind == "organizations"
    assert event.resource_id is None
    assert event.outcome == 201
    assert event.actor_label == "dev@example.test"
    assert event.org_id == default_org_id()
    assert event.actor_id is not None

    invitation_id = created.json()["id"]
    deleted = client.delete(
        f"{INVITATIONS}/{invitation_id}", headers=dev("dev")
    )
    assert deleted.status_code == 204
    (event,) = events_for(deleted.headers["X-Request-ID"])
    assert event.action == "delete"
    assert event.resource_id == invitation_id
    assert event.outcome == 204


def test_get_records_nothing(client):
    response = client.get("/v1alpha1/notebooks", headers=dev("dev"))
    assert response.status_code == 200
    assert events_for(response.headers["X-Request-ID"]) == []


def test_request_that_never_resolved_a_user_is_anonymous(monkeypatch):
    from auth import jwt as auth_jwt

    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.invalid/realms/test")
    auth_jwt.reset_jwks_client()
    with TestClient(create_app()) as anonymous:
        response = anonymous.post("/v1alpha1/notebooks", json={})
    auth_jwt.reset_jwks_client()
    assert response.status_code == 401
    (event,) = events_for(response.headers["X-Request-ID"])
    assert event.actor_label == "anonymous"
    assert event.actor_id is None
    assert event.org_id is None
    assert event.outcome == 401


def test_unhandled_exception_is_recorded_as_500(lenient_client):
    # ServerErrorMiddleware sits outside AuditMiddleware and would
    # otherwise write the 500 itself with no X-Request-ID; AuditMiddleware
    # sends this one itself, with the header, before re-raising.
    response = lenient_client.post(
        BOOM_ROUTE, headers={**dev("dev"), "X-Request-ID": "boom-1"}
    )
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "boom-1"
    (event,) = events_for("boom-1")
    assert event.outcome == 500
    assert event.resource_kind == "test"


def test_client_supplied_request_id_is_echoed_on_a_normal_response(client):
    response = client.get(
        "/v1alpha1/notebooks",
        headers={**dev("dev"), "X-Request-ID": "given-1"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "given-1"


def test_database_error_in_the_middleware_does_not_fail_the_request(
    client, monkeypatch
):
    from audit import middleware as audit_middleware

    def broken():
        raise RuntimeError("database is away")

    monkeypatch.setattr(audit_middleware, "get_db_direct", broken)
    with mock.patch.object(audit_middleware.logger, "warning") as warning:
        response = client.post(
            INVITATIONS,
            json={"email": "unrecorded@example.test", "role": "member"},
            headers=dev("dev"),
        )
    assert response.status_code == 201, response.text
    assert events_for(response.headers["X-Request-ID"]) == []
    warning.assert_called()


# --- the reveal ---------------------------------------------------------------


def test_credential_reveal_records_reveal(client):
    assert (
        client.get("/v1alpha1/notebooks", headers=dev("dev")).status_code
        == 200
    )
    db = get_db_direct()
    try:
        owner = db.query(User).filter(User.sub == "dev").one()
        db.add(
            DBVectorDBInstance(
                id=VDB_ID, org_id=default_org_id(), owner_id=owner.id
            )
        )
        db.add(
            WorkloadCredential(
                resource_kind="vdb",
                resource_id=VDB_ID,
                namespace="ai-stack",
                secret_name="vdb-0000abcd-credentials",
                apikey_secret_name="vdb-0000abcd-apikey-auth",
            )
        )
        db.commit()
    finally:
        db.close()
    try:
        with mock.patch(
            "api.credentials.read_credential_value", return_value="s3cret"
        ):
            response = client.get(
                f"/v1alpha1/credentials/vdb/{VDB_ID}", headers=dev("dev")
            )
        assert response.status_code == 200, response.text
        (event,) = events_for(response.headers["X-Request-ID"])
        assert event.action == "reveal"
        assert event.resource_kind == "credentials"
        assert event.resource_id == str(VDB_ID)
        assert event.outcome == 200
        assert event.detail == {"kind": "vdb"}
    finally:
        db = get_db_direct()
        try:
            db.query(WorkloadCredential).filter(
                WorkloadCredential.resource_id == VDB_ID
            ).delete()
            db.query(DBVectorDBInstance).filter(
                DBVectorDBInstance.id == VDB_ID
            ).delete()
            db.commit()
        finally:
            db.close()


# --- the API ------------------------------------------------------------------


def _seed_events(org_id, count: int) -> list[AuditEvent]:
    db = get_db_direct()
    try:
        rows = [
            AuditEvent(
                at=datetime(2026, 9, 6, 12, 0, i),
                org_id=org_id,
                actor_id=None,
                actor_label="seed@example.test",
                action="create",
                resource_kind="seeded",
                resource_id=None,
                outcome=201,
                request_id=f"seed-{i}",
                detail=None,
            )
            for i in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [r.id for r in rows]
    finally:
        db.close()


def _delete_events(ids):
    db = get_db_direct()
    try:
        db.query(AuditEvent).filter(AuditEvent.id.in_(ids)).delete()
        db.commit()
    finally:
        db.close()


def test_audit_list_is_admin_only(client):
    denied = client.get(AUDIT, headers=dev("alice"))
    assert denied.status_code == 403


def test_audit_list_filters_and_pages_newest_first(client):
    ids = _seed_events(default_org_id(), 3)
    try:
        page = client.get(
            AUDIT,
            params={"resource_kind": "seeded", "limit": 2},
            headers=dev("dev"),
        )
        assert page.status_code == 200, page.text
        body = page.json()
        assert [e["request_id"] for e in body["events"]] == [
            "seed-2",
            "seed-1",
        ]
        assert body["next_cursor"]
        rest = client.get(
            AUDIT,
            params={
                "resource_kind": "seeded",
                "limit": 2,
                "cursor": body["next_cursor"],
            },
            headers=dev("dev"),
        ).json()
        assert [e["request_id"] for e in rest["events"]] == ["seed-0"]
        assert rest["next_cursor"] is None
        by_actor = client.get(
            AUDIT, params={"actor": "seed@"}, headers=dev("dev")
        ).json()
        assert all(
            e["actor_label"] == "seed@example.test" for e in by_actor["events"]
        )
        window = client.get(
            AUDIT,
            params={
                "resource_kind": "seeded",
                "from": "2026-09-06T12:00:01",
                "to": "2026-09-06T12:00:01",
            },
            headers=dev("dev"),
        ).json()
        assert [e["request_id"] for e in window["events"]] == ["seed-1"]
        assert (
            client.get(
                AUDIT, params={"limit": 0}, headers=dev("dev")
            ).status_code
            == 422
        )
        assert (
            client.get(
                AUDIT, params={"limit": 1001}, headers=dev("dev")
            ).status_code
            == 422
        )
    finally:
        _delete_events(ids)


def test_audit_is_scoped_to_the_active_organization(client):
    db = get_db_direct()
    try:
        other_id = (
            db.query(Organization)
            .filter(Organization.slug == "other")
            .one()
            .id
        )
    finally:
        db.close()
    ids = _seed_events(other_id, 1)
    try:
        default_view = client.get(
            AUDIT, params={"resource_kind": "seeded"}, headers=dev("dev")
        ).json()
        assert default_view["events"] == []
        other_view = client.get(
            AUDIT,
            params={"resource_kind": "seeded"},
            headers={**dev("dev"), "X-Org": "other"},
        ).json()
        assert len(other_view["events"]) == 1
    finally:
        _delete_events(ids)


def test_audit_csv_export(client):
    ids = _seed_events(default_org_id(), 2)
    try:
        response = client.get(
            AUDIT,
            params={"resource_kind": "seeded", "format": "csv"},
            headers=dev("dev"),
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().splitlines()
        assert (
            lines[0]
            == "at,actor,action,resource_kind,resource_id,outcome,request_id"
        )
        assert len(lines) == 3
        assert "seed@example.test,create,seeded,,201,seed-1" in lines[1]
    finally:
        _delete_events(ids)


def test_cursor_round_trip():
    from api.audit import decode_cursor, encode_cursor

    at = datetime(2026, 9, 6, 12, 0, 0)
    event_id = uuid.uuid4()
    cursor = encode_cursor(at, event_id)
    assert "=" not in cursor
    assert decode_cursor(cursor) == (at, event_id)


# --- Fix round 1 ----------------------------------------------------------


def test_excluded_path_is_not_recorded(client):
    response = client.post("/v1alpha1/authz/route", headers=dev("dev"))
    assert events_for(response.headers["X-Request-ID"]) == []


def test_tampered_cursor_answers_422(client):
    response = client.get(
        AUDIT, params={"cursor": "not-a-valid-cursor!!"}, headers=dev("dev")
    )
    assert response.status_code == 422


def test_actor_filter_escapes_wildcards(client):
    """A literal ``%`` in the filter must not become a match-everything
    LIKE wildcard."""
    ids = _seed_events(default_org_id(), 1)
    try:
        response = client.get(
            AUDIT,
            params={"resource_kind": "seeded", "actor": "%"},
            headers=dev("dev"),
        )
        assert response.status_code == 200
        assert response.json()["events"] == []
    finally:
        _delete_events(ids)


def test_from_and_to_reject_tz_aware_timestamps(client):
    response = client.get(
        AUDIT,
        params={
            "from": "2026-09-06T12:00:01+00:00",
            "to": "2026-09-06T13:00:00",
        },
        headers=dev("dev"),
    )
    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "from and to must be naive ISO 8601 timestamps"
    )


def _admin_user(is_platform_admin: bool):
    return CurrentUser(
        id=uuid.uuid4(),
        sub="fixture-admin",
        email="fixture-admin@example.test",
        name="Fixture Admin",
        org_id=default_org_id(),
        role="admin",
        is_service=False,
        is_platform_admin=is_platform_admin,
    )


def test_include_anonymous_needs_platform_admin(client):
    org_admin = _admin_user(is_platform_admin=False)
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: org_admin
    try:
        response = client.get(AUDIT, params={"include_anonymous": True})
    finally:
        del app.dependency_overrides[get_current_user]
    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "This action needs the platform admin role"
    )


def test_include_anonymous_shows_null_org_rows_to_platform_admin(client):
    anon_ids = _seed_events(None, 1)
    try:
        without = client.get(
            AUDIT, params={"resource_kind": "seeded"}, headers=dev("dev")
        ).json()
        assert without["events"] == []

        platform_admin = _admin_user(is_platform_admin=True)
        app = client.app
        app.dependency_overrides[get_current_user] = lambda: platform_admin
        try:
            with_anon = client.get(
                AUDIT,
                params={"resource_kind": "seeded", "include_anonymous": True},
            ).json()
        finally:
            del app.dependency_overrides[get_current_user]
        assert [e["request_id"] for e in with_anon["events"]] == ["seed-0"]
    finally:
        _delete_events(anon_ids)


def test_csv_export_streams_beyond_one_page(client):
    org_id = default_org_id()
    base = uuid.UUID("b16a0000-0000-4000-8000-000000000000")
    rows = [
        AuditEvent(
            id=uuid.UUID(int=base.int + i),
            at=datetime(2026, 9, 6, 0, 0, 0) + timedelta(seconds=i),
            org_id=org_id,
            actor_id=None,
            actor_label="page@example.test",
            action="create",
            resource_kind="paged",
            resource_id=None,
            outcome=201,
            request_id=f"page-{i}",
            detail=None,
        )
        for i in range(1500)
    ]
    db = get_db_direct()
    try:
        db.bulk_save_objects(rows)
        db.commit()
    finally:
        db.close()
    try:
        response = client.get(
            AUDIT,
            params={"resource_kind": "paged", "format": "csv"},
            headers=dev("dev"),
        )
        assert response.status_code == 200
        lines = response.text.strip().splitlines()
        assert (
            lines[0]
            == "at,actor,action,resource_kind,resource_id,outcome,request_id"
        )
        # header + all 1500 rows, no truncation marker.
        assert len(lines) == 1501
        assert lines[-1] != "# truncated"
    finally:
        _delete_events([r.id for r in rows])


def test_csv_export_truncates_at_the_row_cap(client, monkeypatch):
    from api import audit as audit_api

    monkeypatch.setattr(audit_api, "CSV_ROW_CAP", 3)
    monkeypatch.setattr(audit_api, "CSV_PAGE_SIZE", 2)
    ids = _seed_events(default_org_id(), 5)
    try:
        response = client.get(
            AUDIT,
            params={"resource_kind": "seeded", "format": "csv"},
            headers=dev("dev"),
        )
        assert response.status_code == 200
        lines = response.text.strip().splitlines()
        # header + 3 (the cap) data rows + the truncation marker.
        assert len(lines) == 5
        assert lines[-1] == "# truncated"
    finally:
        _delete_events(ids)


# --- Fix round 2 (final review, #13 #14 #18) -------------------------------


def test_malformed_client_request_id_is_replaced(client):
    """A request id must look like an id: anything else is dropped in
    favour of a generated one, rather than echoed back verbatim."""
    bad = "not a valid id; =cmd(1,2)"
    response = client.get(
        "/v1alpha1/notebooks",
        headers={**dev("dev"), "X-Request-ID": bad},
    )
    assert response.status_code == 200
    got = response.headers["X-Request-ID"]
    assert got != bad
    uuid.UUID(got)


def test_valid_client_request_id_is_still_echoed(client):
    response = client.get(
        "/v1alpha1/notebooks",
        headers={**dev("dev"), "X-Request-ID": "Valid.id-123"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "Valid.id-123"


def test_csv_export_escapes_formula_prefixes(client):
    ids = _seed_events(default_org_id(), 1)
    db = get_db_direct()
    try:
        db.query(AuditEvent).filter(AuditEvent.id.in_(ids)).update(
            {
                "actor_label": "=cmd|'/c calc'!A0",
                "resource_kind": "@sum(1)",
                "request_id": "-1+1",
            },
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()
    try:
        response = client.get(
            AUDIT,
            params={"actor": "cmd", "format": "csv"},
            headers=dev("dev"),
        )
        assert response.status_code == 200
        lines = response.text.strip().splitlines()
        row = lines[1]
        assert "'=cmd|'/c calc'!A0" in row
        assert "'@sum(1)" in row
        assert "'-1+1" in row
    finally:
        _delete_events(ids)


def test_tz_aware_cursor_is_rejected(client):
    from api.audit import encode_cursor

    cursor = encode_cursor(
        datetime.fromisoformat("2026-09-06T12:00:00+00:00"), uuid.uuid4()
    )
    response = client.get(AUDIT, params={"cursor": cursor}, headers=dev("dev"))
    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "from and to must be naive ISO 8601 timestamps"
    )


def test_send_internal_error_failure_still_reraises_and_records(
    lenient_client, monkeypatch
):
    """A broken send (for example a client that already disconnected) must
    not swallow the original exception nor crash the middleware."""
    from audit import middleware as audit_middleware

    async def broken_send(send, request_id):
        raise RuntimeError("send is broken too")

    monkeypatch.setattr(audit_middleware, "_send_internal_error", broken_send)
    with mock.patch.object(audit_middleware.logger, "warning") as warning:
        response = lenient_client.post(
            BOOM_ROUTE, headers={**dev("dev"), "X-Request-ID": "boom-send-1"}
        )
    # ServerErrorMiddleware's own fallback (no X-Request-ID) since ours
    # could not be sent.
    assert response.status_code == 500
    warning.assert_called()
    (event,) = events_for("boom-send-1")
    assert event.outcome == 500


def test_exception_after_response_started_is_recorded_as_aborted(
    lenient_client,
):
    response = lenient_client.post(
        BOOM_STARTED_ROUTE,
        headers={**dev("dev"), "X-Request-ID": "boom-started-1"},
    )
    assert response.status_code == 200
    (event,) = events_for("boom-started-1")
    assert event.outcome == 200
    assert event.detail == {"aborted": True}
