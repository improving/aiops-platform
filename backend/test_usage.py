"""``GET /v1alpha1/organizations/current/usage``: LiteLLM spend logs
aggregated by user, target and day (Task 2 of the usage-and-metrics
plan)."""

import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import api.organizations as orgs
from auth.current_user import CurrentUser, get_current_user
from core import create_app
from db.database import get_db_direct
from models.organization import Organization
from models.user import User
from utils import litellm as ll

# ``end_user`` carries the platform user id (``user_key``); the usage
# endpoint maps it back to the email from the ``users`` table.
ALICE_ID = "a11ce000-1111-4111-8111-111111111111"
BOB_ID = "b0b00000-2222-4222-8222-222222222222"

ROWS = [
    {
        "model_group": "inst-aaaaaaaa",
        "end_user": ALICE_ID,
        "startTime": "2026-09-01T10:00:00Z",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "spend": 0.5,
    },
    {
        "model_group": "inst-aaaaaaaa",
        "end_user": ALICE_ID,
        "startTime": "2026-09-02T10:00:00Z",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "spend": 0.05,
    },
    {
        "model_group": "inst-bbbbbbbb",
        "end_user": BOB_ID,
        "startTime": "2026-09-01T10:00:00Z",
        "prompt_tokens": 200,
        "completion_tokens": 100,
        "spend": 1.0,
    },
    {
        # Made with the master key before per-user attribution shipped.
        "model_group": "inst-aaaaaaaa",
        "end_user": "",
        "startTime": "2026-09-01T09:00:00Z",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "spend": 0.01,
    },
]


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _mock_litellm(rows=ROWS, capped=False):
    litellm = mock.Mock()
    litellm.spend_logs.return_value = (rows, capped)
    return litellm


def _fake_ensure(db, org, core_v1=None):
    org.litellm_team_id = "t-1"
    return "sk-virtual"


def _default_org():
    db = get_db_direct()
    try:
        return (
            db.query(Organization)
            .filter(Organization.slug == "default")
            .first()
        )
    finally:
        db.close()


def _add_user(user_id: str, email: str) -> None:
    db = get_db_direct()
    try:
        db.merge(
            User(id=uuid.UUID(user_id), sub=f"usage:{email}", email=email)
        )
        db.commit()
    finally:
        db.close()


def _member(email: str, org_id, user_id: str) -> CurrentUser:
    return CurrentUser(
        id=uuid.UUID(user_id),
        sub=email,
        email=email,
        name=email,
        org_id=org_id,
        role="member",
        is_service=False,
    )


def test_usage_needs_litellm_configured(client, monkeypatch):
    monkeypatch.setattr(orgs, "get_client", lambda: None)
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 503


def test_usage_days_out_of_range_is_422(client):
    assert (
        client.get("/v1alpha1/organizations/current/usage?days=0").status_code
        == 422
    )
    assert (
        client.get("/v1alpha1/organizations/current/usage?days=91").status_code
        == 422
    )


def test_usage_502_on_litellm_error(client, monkeypatch):
    litellm = mock.Mock()
    litellm.spend_logs.side_effect = ll.LiteLLMError("down")
    monkeypatch.setattr(orgs, "get_client", lambda: litellm)
    monkeypatch.setattr(orgs, "ensure_org_key", _fake_ensure)
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 502


def test_usage_admin_sees_every_user_and_the_unattributed_row(
    client, monkeypatch
):
    litellm = _mock_litellm()
    monkeypatch.setattr(orgs, "get_client", lambda: litellm)
    monkeypatch.setattr(orgs, "ensure_org_key", _fake_ensure)
    _add_user(ALICE_ID, "alice@example.com")

    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["scope"] == "organization"
    assert body["capped"] is False
    assert body["totals"] == {
        "requests": 4,
        "prompt_tokens": 311,
        "completion_tokens": 156,
        "spend": pytest.approx(1.56),
    }

    by_target = {t["target"]: t for t in body["by_target"]}
    assert list(by_target) == ["inst-bbbbbbbb", "inst-aaaaaaaa"]
    assert by_target["inst-bbbbbbbb"]["spend"] == pytest.approx(1.0)
    assert by_target["inst-aaaaaaaa"]["spend"] == pytest.approx(0.56)
    assert by_target["inst-aaaaaaaa"]["requests"] == 3

    # Alice resolves to her email; Bob has no user row, so his id shows.
    users = {r["user"] for r in body["rows"]}
    assert users == {"alice@example.com", BOB_ID, None}
    days = [r["day"] for r in body["rows"]]
    assert days == sorted(days, reverse=True)
    # Admins read the whole team: no server-side end_user filter.
    assert litellm.spend_logs.call_args.args[3] is None


def test_usage_member_sees_only_their_own_rows(client, monkeypatch):
    litellm = _mock_litellm()
    monkeypatch.setattr(orgs, "get_client", lambda: litellm)
    monkeypatch.setattr(orgs, "ensure_org_key", _fake_ensure)
    _add_user(BOB_ID, "bob@example.com")
    bob = _member("bob@example.com", _default_org().id, BOB_ID)

    app = client.app
    app.dependency_overrides[get_current_user] = lambda: bob
    try:
        response = client.get("/v1alpha1/organizations/current/usage")
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "user"
    assert {r["user"] for r in body["rows"]} == {"bob@example.com"}
    assert body["totals"]["requests"] == 1
    assert body["totals"]["spend"] == pytest.approx(1.0)
    # Members ask LiteLLM for their own rows only.
    assert litellm.spend_logs.call_args.args[3] == BOB_ID


def test_usage_503_without_a_litellm_team(client, monkeypatch):
    monkeypatch.setattr(orgs, "get_client", lambda: _mock_litellm())
    monkeypatch.setattr(
        orgs,
        "ensure_org_key",
        lambda db, org, core_v1=None: setattr(org, "litellm_team_id", None),
    )
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 503
    assert "team" in response.json()["detail"]


def test_usage_labels_deleted_targets(client, monkeypatch):
    rows = [
        {**ROWS[0], "model_group": "inst-deadbeef"},
        {**ROWS[0], "model_group": "prov-deadbeef/gpt-x"},
        {**ROWS[0], "model_group": "other"},
    ]
    monkeypatch.setattr(orgs, "get_client", lambda: _mock_litellm(rows))
    monkeypatch.setattr(orgs, "ensure_org_key", _fake_ensure)
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200, response.text
    labels = {t["target"]: t["label"] for t in response.json()["by_target"]}
    assert labels == {
        "inst-deadbeef": "inst-deadbeef (deleted)",
        "prov-deadbeef/gpt-x": "prov-deadbeef/gpt-x (deleted)",
        "other": "other",
    }


def test_usage_capped_passes_through(client, monkeypatch):
    monkeypatch.setattr(
        orgs, "get_client", lambda: _mock_litellm(rows=[], capped=True)
    )
    monkeypatch.setattr(orgs, "ensure_org_key", _fake_ensure)
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200
    assert response.json()["capped"] is True


def test_usage_mock_mode_serves_canned_rows(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"]["requests"] == 3
    assert {r["user"] for r in body["rows"]} == {
        "dev@example.test",
        "someone@example.com",
    }
    assert [(t["target"], t["label"]) for t in body["by_target"]] == [
        ("inst-mock", "Mock model · Mock")
    ]
