"""``GET /v1alpha1/organizations/current/usage``: LiteLLM spend logs
aggregated by user, target and day (Task 2 of the usage-and-metrics
plan)."""

import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import api.usage as usage
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
    """Returns ``rows`` for the team and the ``end_user`` query alike (it
    ignores that filter, which is what the ``_visible_to`` backstop tests
    rely on) and nothing for a member's second query, the rows of keys
    they own (``user_id``)."""

    def spend_logs(team_id, start, end, end_user=None, user_id=None):
        return ([], False) if user_id else (rows, capped)

    litellm = mock.Mock()
    litellm.spend_logs.side_effect = spend_logs
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
    monkeypatch.setattr(usage, "get_client", lambda: None)
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
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 502


def test_usage_admin_sees_every_user_and_the_unattributed_row(
    client, monkeypatch
):
    litellm = _mock_litellm()
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
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
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
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
    assert litellm.spend_logs.call_args_list[0].args[3] == BOB_ID


def test_usage_503_without_a_litellm_team(client, monkeypatch):
    monkeypatch.setattr(usage, "get_client", lambda: _mock_litellm())
    monkeypatch.setattr(
        usage,
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
    monkeypatch.setattr(usage, "get_client", lambda: _mock_litellm(rows))
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
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
        usage, "get_client", lambda: _mock_litellm(rows=[], capped=True)
    )
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200
    assert response.json()["capped"] is True


def test_mcp_calls_are_tools_not_model_requests():
    """LiteLLM logs an MCP call as a spend row named like a model. It is
    no model request: own list, server and tool by name, the listing of
    tools left out."""
    from api.usage import _aggregate_tools, _is_mcp_row

    rows = [
        {"model": "MCP: list_tools"},
        {"model": "MCP: deepwiki87aa1a35-read_wiki_structure"},
        {"model": "MCP: deepwiki87aa1a35-read_wiki_structure"},
        {"model": "MCP: gone0000abcd-query-docs"},
        {"model_group": "inst-aaaaaaaa", "model": "openai/qwen"},
    ]
    assert [_is_mcp_row(r) for r in rows] == [True, True, True, True, False]
    tools = _aggregate_tools(
        [r for r in rows if _is_mcp_row(r)], {"deepwiki87aa1a35": "deepwiki"}
    )
    assert tools == [
        {"server": "deepwiki", "tool": "read_wiki_structure", "calls": 2},
        # A deleted server keeps its alias; a tool name may hold a "-".
        {"server": "gone0000abcd", "tool": "query-docs", "calls": 1},
    ]


def test_usage_mock_mode_serves_canned_rows(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    # The three model requests; the mock's MCP rows are not among them.
    assert body["totals"]["requests"] == 3
    assert body["tools"] == [
        {"server": "mock00000000", "tool": "echo", "calls": 2}
    ]
    assert all(not t["target"].startswith("MCP") for t in body["by_target"])
    assert {r["user"] for r in body["rows"]} == {
        "dev@example.test",
        "someone@example.com",
    }
    assert [(t["target"], t["label"]) for t in body["by_target"]] == [
        ("inst-mock", "Mock model · Mock")
    ]


def test_usage_merges_rows_of_one_person_under_two_end_user_values(
    client, monkeypatch
):
    """Rows written while ``user_key`` returned the email carry it as
    ``end_user``; rows written after the switch to user ids carry the
    id. Both map to the same display name, so they must land in one
    row per target and day: the UI keys its table rows by (user,
    target, day)."""
    rows = [
        {
            "model_group": "inst-aaaaaaaa",
            "end_user": ALICE_ID,
            "startTime": "2026-09-06T10:00:00Z",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "spend": 0.05,
        },
        {
            "model_group": "inst-aaaaaaaa",
            "end_user": "alice@example.com",
            "startTime": "2026-09-06T11:00:00Z",
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "spend": 0.10,
        },
    ]
    litellm = _mock_litellm(rows)
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    _add_user(ALICE_ID, "alice@example.com")

    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200, response.text
    body = response.json()

    keys = [(r["user"], r["target"], r["day"]) for r in body["rows"]]
    assert keys == [("alice@example.com", "inst-aaaaaaaa", "2026-09-06")]
    assert body["rows"][0]["requests"] == 2
    assert body["rows"][0]["spend"] == pytest.approx(0.15)


def test_usage_keeps_two_people_apart_on_one_target_and_day(
    client, monkeypatch
):
    """Two different users on the same target and day must stay two
    rows: only rows that resolve to the same display name merge."""
    rows = [
        {
            "model_group": "inst-aaaaaaaa",
            "end_user": ALICE_ID,
            "startTime": "2026-09-06T10:00:00Z",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "spend": 0.05,
        },
        {
            "model_group": "inst-aaaaaaaa",
            "end_user": BOB_ID,
            "startTime": "2026-09-06T11:00:00Z",
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "spend": 0.10,
        },
    ]
    litellm = _mock_litellm(rows)
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    _add_user(ALICE_ID, "alice@example.com")
    _add_user(BOB_ID, "bob@example.com")

    response = client.get("/v1alpha1/organizations/current/usage")
    assert response.status_code == 200, response.text
    body = response.json()

    by_user = {r["user"]: r for r in body["rows"]}
    assert set(by_user) == {"alice@example.com", "bob@example.com"}
    assert by_user["alice@example.com"]["requests"] == 1
    assert by_user["bob@example.com"]["requests"] == 1


def test_usage_member_does_not_see_their_email_keyed_rows(client, monkeypatch):
    """Pins the current asymmetry: an admin merges a member's
    email-keyed and id-keyed rows into one (see the test above and
    ``test_usage_merges_rows_of_one_person_under_two_end_user_values``),
    but a member's own request only ever asks LiteLLM for their user
    id, so their email-keyed rows never come back. A change in either
    direction should be deliberate, not accidental."""
    rows = [
        {
            "model_group": "inst-aaaaaaaa",
            "end_user": BOB_ID,
            "startTime": "2026-09-06T10:00:00Z",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "spend": 0.05,
        },
        {
            "model_group": "inst-aaaaaaaa",
            "end_user": "bob@example.com",
            "startTime": "2026-09-06T11:00:00Z",
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "spend": 0.10,
        },
    ]
    # The mock ignores the ``end_user`` filter argument and always
    # returns both rows, so the backstop ``_visible_to`` is what drops
    # the email-keyed one.
    litellm = _mock_litellm(rows)
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
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
    assert len(body["rows"]) == 1
    assert body["rows"][0]["requests"] == 1
    assert litellm.spend_logs.call_args_list[0].args[3] == BOB_ID


def _langflow_row(owner: str, request_id: str, end_user: str = "") -> dict:
    """A row of a call made straight to LiteLLM with a member's own key
    (utils.litellm.ensure_user_key), the way a Langflow flow calls it:
    the request names no ``user``, the key's owner is on the row."""
    return {
        "request_id": request_id,
        "model_group": "inst-aaaaaaaa",
        "end_user": end_user,
        "user": owner,
        "metadata": {"user_api_key_user_id": owner},
        "startTime": "2026-09-01T11:00:00Z",
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "spend": 2.0,
    }


def test_usage_attributes_a_row_to_the_owner_of_its_key(client, monkeypatch):
    rows = [*ROWS, _langflow_row(ALICE_ID, "req-flow-1")]
    litellm = _mock_litellm(rows)
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    _add_user(ALICE_ID, "alice@example.com")

    body = client.get("/v1alpha1/organizations/current/usage").json()

    # Alice's chat row and her flow's row of that day and target are one
    # line; the flow's row is not "unattributed".
    alice_day_one = [
        r
        for r in body["rows"]
        if r["user"] == "alice@example.com" and r["day"] == "2026-09-01"
    ]
    assert len(alice_day_one) == 1
    assert alice_day_one[0]["requests"] == 2
    assert alice_day_one[0]["spend"] == pytest.approx(2.5)
    unattributed = [r for r in body["rows"] if r["user"] is None]
    assert [r["requests"] for r in unattributed] == [1]


def test_usage_trusts_the_key_owner_over_the_requests_user(
    client, monkeypatch
):
    # With a key of their own a member writes the request, `user` field
    # included; only the key's owner is something they cannot choose.
    rows = [_langflow_row(BOB_ID, "req-spoof", end_user=ALICE_ID)]
    litellm = _mock_litellm(rows)
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    _add_user(ALICE_ID, "alice@example.com")
    _add_user(BOB_ID, "bob@example.com")

    body = client.get("/v1alpha1/organizations/current/usage").json()
    assert {r["user"] for r in body["rows"]} == {"bob@example.com"}


def test_usage_member_sees_the_rows_of_their_own_key(client, monkeypatch):
    chat_row = {**ROWS[2], "request_id": "req-chat-1"}
    flow_row = _langflow_row(BOB_ID, "req-flow-2")

    def spend_logs(team_id, start, end, end_user=None, user_id=None):
        # LiteLLM filters on the server: one query finds the rows that
        # name Bob as the request's user, the other the rows of his key.
        if end_user == BOB_ID and user_id is None:
            return [chat_row], False
        if user_id == BOB_ID and end_user is None:
            return [flow_row], False
        raise AssertionError((end_user, user_id))

    litellm = mock.Mock()
    litellm.spend_logs.side_effect = spend_logs
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    _add_user(BOB_ID, "bob@example.com")
    bob = _member("bob@example.com", _default_org().id, BOB_ID)

    app = client.app
    app.dependency_overrides[get_current_user] = lambda: bob
    try:
        body = client.get("/v1alpha1/organizations/current/usage").json()
    finally:
        del app.dependency_overrides[get_current_user]

    assert body["scope"] == "user"
    assert {r["user"] for r in body["rows"]} == {"bob@example.com"}
    assert body["totals"]["requests"] == 2
    assert body["totals"]["spend"] == pytest.approx(3.0)
    assert litellm.spend_logs.call_count == 2


def test_usage_member_counts_a_row_found_by_both_queries_once(
    client, monkeypatch
):
    both = _langflow_row(BOB_ID, "req-both", end_user=BOB_ID)
    litellm = mock.Mock()
    litellm.spend_logs.return_value = ([both], False)
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)
    _add_user(BOB_ID, "bob@example.com")
    bob = _member("bob@example.com", _default_org().id, BOB_ID)

    app = client.app
    app.dependency_overrides[get_current_user] = lambda: bob
    try:
        body = client.get("/v1alpha1/organizations/current/usage").json()
    finally:
        del app.dependency_overrides[get_current_user]
    assert body["totals"]["requests"] == 1


def test_usage_leaves_a_master_key_row_unattributed(client, monkeypatch):
    # Measured on LiteLLM 1.99: the master key is owned by LiteLLM's own
    # "default_user_id", which lands in both owner fields of its rows.
    # That is not a person: only a platform user id (a UUID) counts.
    row = {
        **_langflow_row("default_user_id", "req-master"),
        "end_user": "",
    }
    litellm = _mock_litellm([row])
    monkeypatch.setattr(usage, "get_client", lambda: litellm)
    monkeypatch.setattr(usage, "ensure_org_key", _fake_ensure)

    body = client.get("/v1alpha1/organizations/current/usage").json()
    assert [r["user"] for r in body["rows"]] == [None]


def test_merge_rows_keeps_rows_that_have_no_request_id():
    a, b = {"spend": 1}, {"spend": 2}
    same = {"request_id": "r-1"}
    assert usage._merge_rows([a, same], [b, {"request_id": "r-1"}]) == [
        a,
        same,
        b,
    ]
