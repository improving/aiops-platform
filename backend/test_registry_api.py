"""api/registry.py: search/import/manual/patch/sync/delete, admin
writes, member visibility of published rows only, and the daily
sync job's best-effort error handling (registry/sync.py).

AIOPS_CHAT_MOCK=true (needs TEST_MODE, set in conftest.py) makes
search()/fetch() read backend/test_fixtures/ instead of the network,
the same fixture the fast Playwright tier would import from.
"""

import uuid

from fastapi.testclient import TestClient

from core import create_app
from db.database import get_db_direct
from models.inference_instance import DBInferenceInstance
from models.models import DBModel
from testing.tokens import bearer, make_token
from utils import genid

MOCK_SOURCE_ID = "Qwen/Qwen3-0.6B-GGUF"


def _delete_model_row(model_id):
    db = get_db_direct()
    try:
        mid = (
            model_id
            if isinstance(model_id, uuid.UUID)
            else uuid.UUID(model_id)
        )
        db.query(DBModel).filter(DBModel.id == mid).delete()
        db.commit()
    finally:
        db.close()


def test_search_mock_mode_returns_the_fixture_preview(monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/v1alpha1/registry/search",
        params={"source": "huggingface", "q": "qwen"},
    )
    assert response.status_code == 200, response.text
    results = response.json()
    assert len(results) == 1
    entry = results[0]
    assert entry["source"] == "huggingface"
    assert entry["source_id"] == MOCK_SOURCE_ID
    assert entry["already_imported"] is False
    assert entry["serving_options"] == [
        {
            "engine": "Ollama",
            "reference": f"hf.co/{MOCK_SOURCE_ID}:Q8_0",
            "default_args": None,
        }
    ]


def test_search_needs_an_admin(monkeypatch, oidc_client, rsa_key):  # noqa: F811
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    member = bearer(
        make_token(rsa_key, sub="registry-member-1", roles=("member",))
    )
    response = oidc_client.get(
        "/v1alpha1/registry/search",
        params={"source": "huggingface", "q": "qwen"},
        headers=member,
    )
    assert response.status_code == 403


def test_import_creates_a_draft_with_serving_options_and_409_on_repeat(
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    app = create_app()
    client = TestClient(app)

    created = client.post(
        "/v1alpha1/registry/import",
        json={"source": "huggingface", "source_id": MOCK_SOURCE_ID},
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["status"] == "draft"
    assert entry["source"] == "huggingface"
    assert entry["source_id"] == MOCK_SOURCE_ID
    assert entry["synced_at"] is None
    assert entry["serving_options"]
    model_id = entry["id"]

    try:
        # not yet visible on the members' catalog (still a draft)
        catalog = {m["id"] for m in client.get("/v1alpha1/models").json()}
        assert model_id not in catalog

        repeat = client.post(
            "/v1alpha1/registry/import",
            json={"source": "huggingface", "source_id": MOCK_SOURCE_ID},
        )
        assert repeat.status_code == 409
    finally:
        _delete_model_row(model_id)


def test_import_with_an_explicit_status(monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    app = create_app()
    client = TestClient(app)

    created = client.post(
        "/v1alpha1/registry/import",
        json={
            "source": "huggingface",
            "source_id": MOCK_SOURCE_ID,
            "status": "published",
        },
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    try:
        assert created.json()["status"] == "published"
        catalog = {m["id"] for m in client.get("/v1alpha1/models").json()}
        assert model_id in catalog
    finally:
        _delete_model_row(model_id)


def test_member_cannot_see_a_draft_until_published(
    monkeypatch,
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    admin = bearer(
        make_token(rsa_key, sub="registry-admin-1", roles=("admin",))
    )
    member = bearer(
        make_token(rsa_key, sub="registry-member-2", roles=("member",))
    )

    created = oidc_client.post(
        "/v1alpha1/registry/import",
        json={"source": "huggingface", "source_id": MOCK_SOURCE_ID},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]

    try:
        listed = oidc_client.get("/v1alpha1/models", headers=member).json()
        assert model_id not in {m["id"] for m in listed}
        # admin-only registry endpoint denies the member outright too.
        denied = oidc_client.get(
            f"/v1alpha1/registry/{model_id}/sync", headers=member
        )
        assert denied.status_code in (403, 405)

        published = oidc_client.patch(
            f"/v1alpha1/registry/{model_id}",
            json={"status": "published"},
            headers=admin,
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"

        listed = oidc_client.get("/v1alpha1/models", headers=member).json()
        assert model_id in {m["id"] for m in listed}
    finally:
        _delete_model_row(model_id)


def test_manual_create_is_published_with_its_serving_options():
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/v1alpha1/registry/manual",
        json={
            "name": "Manual Model",
            "model_id": "org/manual-model",
            "category": "llm",
            "serving_options": [
                {"engine": "HuggingFace", "reference": "org/manual-model"}
            ],
        },
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    try:
        assert entry["source"] == "manual"
        assert entry["status"] == "published"
        assert [
            (o["engine"], o["reference"]) for o in entry["serving_options"]
        ] == [("HuggingFace", "org/manual-model")]
    finally:
        _delete_model_row(entry["id"])


def test_sync_updates_synced_at_and_metadata(monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    app = create_app()
    client = TestClient(app)

    created = client.post(
        "/v1alpha1/registry/import",
        json={"source": "huggingface", "source_id": MOCK_SOURCE_ID},
    ).json()
    model_id = created["id"]
    assert created["synced_at"] is None

    try:
        synced = client.post(f"/v1alpha1/registry/{model_id}/sync")
        assert synced.status_code == 200, synced.text
        entry = synced.json()
        assert entry["synced_at"] is not None
        assert entry["sync_error"] is None
    finally:
        _delete_model_row(model_id)


def test_delete_blocked_by_an_inference_instance():
    app = create_app()
    client = TestClient(app)
    models = {m["modelId"]: m for m in client.get("/v1alpha1/models").json()}
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    model_id = models["qwen3:0.6b"]["id"]

    db = get_db_direct()
    try:
        instance = DBInferenceInstance(
            id=genid.uuid4(),
            model_id=uuid.UUID(model_id),
            engine_id=uuid.UUID(engines["Ollama"]["id"]),
        )
        db.add(instance)
        db.commit()
        instance_id = instance.id
    finally:
        db.close()

    try:
        response = client.delete(f"/v1alpha1/registry/{model_id}")
        assert response.status_code == 409
        assert "inference instances" in response.json()["detail"]
    finally:
        db = get_db_direct()
        try:
            db.query(DBInferenceInstance).filter(
                DBInferenceInstance.id == instance_id
            ).delete()
            db.commit()
        finally:
            db.close()


def test_sync_published_swallows_a_source_error_and_records_it(monkeypatch):
    from registry import sync as sync_module
    from registry.entry import SourceError

    db = get_db_direct()
    model = DBModel(
        id=genid.uuid4(),
        name="Sync Failure Test",
        modelId="org/sync-failure-test",
        category="llm",
        source="huggingface",
        source_id="org/sync-failure-test",
        status="published",
    )
    db.add(model)
    db.commit()
    model_id = model.id
    db.close()

    def boom(source, source_id):
        raise SourceError(429, "rate limited; retry after 30")

    monkeypatch.setattr(sync_module.sources, "fetch", boom)

    try:
        db = get_db_direct()
        try:
            sync_module.sync_published(db)
        finally:
            db.close()

        db = get_db_direct()
        try:
            refreshed = (
                db.query(DBModel).filter(DBModel.id == model_id).first()
            )
            assert refreshed.sync_error == "rate limited; retry after 30"
        finally:
            db.close()
    finally:
        _delete_model_row(model_id)


def test_sync_published_clears_a_previous_error_on_success(monkeypatch):
    from registry import sync as sync_module
    from registry.entry import RegistryEntry

    db = get_db_direct()
    model = DBModel(
        id=genid.uuid4(),
        name="Sync Recovery Test",
        modelId="org/sync-recovery-test",
        category="llm",
        source="huggingface",
        source_id="org/sync-recovery-test",
        status="published",
        sync_error="stale error from a previous run",
    )
    db.add(model)
    db.commit()
    model_id = model.id
    db.close()

    def recovered(source, source_id):
        return RegistryEntry(
            source=source,
            source_id=source_id,
            name="Sync Recovery Test",
            description=None,
            category="llm",
            subcategory=None,
            size=123,
            license="mit",
            parameters=None,
            context_length=None,
            capabilities=["chat"],
            formats=["safetensors"],
            tags=[],
            raw={"ok": True},
        )

    monkeypatch.setattr(sync_module.sources, "fetch", recovered)

    try:
        db = get_db_direct()
        try:
            sync_module.sync_published(db)
        finally:
            db.close()

        db = get_db_direct()
        try:
            refreshed = (
                db.query(DBModel).filter(DBModel.id == model_id).first()
            )
            assert refreshed.sync_error is None
            assert refreshed.license == "mit"
            assert refreshed.synced_at is not None
        finally:
            db.close()
    finally:
        _delete_model_row(model_id)
