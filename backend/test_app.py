import json
import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api.inference_status import missing_endpoint_clause
from core import create_app
from db.database import get_db_direct
from models.models import DBModel
from models.serving_option import ServingOption
from schemas.notebook import NOTEBOOK_NAME_MAX_LENGTH
from testing.tokens import bearer, make_token
from utils import genid
from utils.kubernetes_utils import PodStatus


def test_missing_endpoint_clause_compiles_to_is_null():
    sql = str(missing_endpoint_clause().compile())
    assert "IS NULL" in sql
    assert "endpoint = " in sql


def test_lifespan_skips_scheduler_in_test_mode():
    app = create_app(setup_db=False)
    with TestClient(app) as client:
        assert getattr(app.state, "scheduler", None) is None
        assert client.get("/health").status_code == 200


def test_lifespan_runs_scheduler(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "false")
    # Outside TEST_MODE the API insists on real authentication; the JWKS
    # is fetched lazily, so a dummy issuer is enough to start.
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.invalid/realms/test")
    app = create_app(setup_db=False)
    with TestClient(app) as client:
        scheduler = app.state.scheduler
        assert scheduler.running
        # The 3 endpoint-polling jobs, the MCP instances poller and the
        # daily registry sync.
        assert len(scheduler.get_jobs()) == 5
        assert client.get("/health").status_code == 200
    assert not scheduler.running
    assert app.state.scheduler is None


def test_health_endpoint():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"message": "OK"}


@pytest.mark.parametrize(
    ("name", "endpoint"),
    [
        ("models", "/v1alpha1/models"),
        ("engines", "/v1alpha1/engines"),
        ("inferenceInstance", "/v1alpha1/inferenceInstance"),
        # ("hosts", "/v1alpha1/hosts"),
        ("vectordb", "/v1alpha1/vectordb"),
        ("vectordb_instances", "/v1alpha1/vectordb_instances"),
        ("notebooks", "/v1alpha1/notebooks"),
    ],
)
def test_get_apis(snapshot, name, endpoint):
    app = create_app()
    client = TestClient(app)
    response = client.get(endpoint)
    assert response.status_code == 200
    snapshot.assert_match(
        json.dumps(response.json(), indent=2), f"{name}.json"
    )


def test_model_create_delete(snapshot):
    app = create_app(setup_db=False)
    client = TestClient(app)

    # Create model
    response = client.post(
        "/v1alpha1/models",
        json={
            "name": "Mistral-7B-v4",
            "modelId": "mistralai/Mistral-7B-v4",
            "description": "Mistral-7B-v4",
            "category": "llm",
            "subcategory": "text generation",
            "size": 16106127360,
            "countAdapters": 0,
        },
    )
    assert response.status_code == 200
    model_id = response.json()["id"]
    print(model_id)
    assert model_id is not None
    # List models and check if the model is present
    response = client.get("/v1alpha1/models")
    assert response.status_code == 200
    model_list = response.json()
    assert any(model["id"] == model_id for model in model_list)
    # Delete model
    response = client.delete(f"/v1alpha1/models/{model_id}")
    assert response.status_code == 200
    snapshot.assert_match(
        json.dumps(response.json(), indent=2), "model-delete.json"
    )


def _notebook_payload(name):
    return {
        "name": name,
        "type": "vscode",
        "framework": "python",
        "nvidia_gpu": False,
    }


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("has space", id="space"),
        pytest.param("Upper", id="uppercase"),
        pytest.param("a" * 64, id="64-chars"),
    ],
)
def test_create_notebook_rejects_invalid_name(name):
    app = create_app(setup_db=False)
    client = TestClient(app)
    with mock.patch("api.notebooks.NotebooksController") as controller_cls:
        response = client.post(
            "/v1alpha1/notebooks", json=_notebook_payload(name)
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "name"]
    assert "lowercase" in detail[0]["msg"]
    assert str(NOTEBOOK_NAME_MAX_LENGTH) in detail[0]["msg"]
    controller_cls.return_value.install.assert_not_called()


def test_create_notebook_rejects_duplicate_name():
    app = create_app(setup_db=False)
    client = TestClient(app)
    with mock.patch("api.notebooks.NotebooksController") as controller_cls:
        controller_cls.return_value.install = mock.AsyncMock()
        first = client.post(
            "/v1alpha1/notebooks", json=_notebook_payload("nb")
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/v1alpha1/notebooks", json=_notebook_payload("nb")
        )
        # Another namespace is a different notebook.
        other_ns = client.post(
            "/v1alpha1/notebooks",
            json={**_notebook_payload("nb"), "namespace": "other"},
        )
        assert second.status_code == 409
        assert second.json()["detail"] == "Notebook 'nb' already exists"
        assert other_ns.status_code == 200, other_ns.text
        assert controller_cls.return_value.install.await_count == 2
        # The tests share one database, so remove what this test created.
        controller_cls.return_value.uninstall = mock.AsyncMock()
        for created in (first, other_ns):
            deleted = client.delete(
                f"/v1alpha1/notebooks/{created.json()['id']}"
            )
            assert deleted.status_code == 200, deleted.text
    assert client.get("/v1alpha1/notebooks").json() == []


def test_create_vectordb_instance_without_cluster_leaves_no_row(monkeypatch):
    import api.vectordb_instance as vi

    def boom(*args, **kwargs):
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(vi, "VectorDBController", boom)
    app = create_app()
    client = TestClient(app)
    vectordb = client.get("/v1alpha1/vectordb").json()[0]
    before = len(client.get("/v1alpha1/vectordb_instances").json())
    response = client.post(
        "/v1alpha1/vectordb_instances",
        json={"vectorDB": {"id": vectordb["id"]}, "configParams": {}},
    )
    assert response.status_code == 503
    assert "Kubernetes is not reachable" in response.json()["detail"]
    assert len(client.get("/v1alpha1/vectordb_instances").json()) == before


@pytest.fixture
def vectordb_env(monkeypatch):
    """A mocked controller and credential store around the vector DB
    instance endpoints; yields (client, controller, calls) where calls
    records every credential helper call in order."""
    import api.vectordb_instance as vi

    controller_cls = mock.Mock()
    controller = controller_cls.return_value
    controller.namespace = "ai-stack"
    controller.install = mock.AsyncMock()
    controller.uninstall = mock.AsyncMock()
    monkeypatch.setattr(vi, "VectorDBController", controller_cls)
    monkeypatch.setattr(
        vi,
        "get_pod_status_and_readiness",
        lambda *a, **k: PodStatus(False, "Pending"),
    )
    calls = mock.Mock()
    calls.generate_secret.return_value = "s3cret"
    monkeypatch.setattr(vi, "generate_secret", calls.generate_secret)
    monkeypatch.setattr(vi, "store_credential", calls.store_credential)
    monkeypatch.setattr(vi, "delete_credential", calls.delete_credential)
    return TestClient(create_app()), controller, calls


def _create_vectordb(client):
    vectordb = client.get("/v1alpha1/vectordb").json()[0]
    return client.post(
        "/v1alpha1/vectordb_instances",
        json={"vectorDB": {"id": vectordb["id"]}, "configParams": {}},
    )


def test_create_vectordb_instance_stores_a_credential_before_install(
    vectordb_env,
):
    import uuid

    client, controller, calls = vectordb_env
    created = _create_vectordb(client)
    assert created.status_code == 201, created.text
    instance_id = uuid.UUID(created.json()["id"])

    calls.generate_secret.assert_called_once_with(seed=str(instance_id))
    store = calls.store_credential.call_args
    assert store.args[1:] == ("ai-stack", "vdb", instance_id, "s3cret")
    controller.install.assert_awaited_once()
    assert controller.install.await_args.kwargs == {"credential": "s3cret"}
    assert controller.install.await_args.args[0].id == instance_id
    calls.delete_credential.assert_not_called()

    deleted = client.delete(f"/v1alpha1/vectordb_instances/{instance_id}")
    assert deleted.status_code == 204, deleted.text
    controller.uninstall.assert_awaited_once()
    delete = calls.delete_credential.call_args
    assert delete.args[1:] == ("ai-stack", "vdb", instance_id)
    ids = [i["id"] for i in client.get("/v1alpha1/vectordb_instances").json()]
    assert str(instance_id) not in ids


def _ids(client):
    return {i["id"] for i in client.get("/v1alpha1/vectordb_instances").json()}


def _rows(client):
    return {
        i["id"]: i for i in client.get("/v1alpha1/vectordb_instances").json()
    }


def test_create_vectordb_instance_install_failure_keeps_the_row(
    vectordb_env,
):
    client, controller, calls = vectordb_env
    controller.install.side_effect = RuntimeError("helm exploded")
    before = _ids(client)

    created = _create_vectordb(client)

    assert created.status_code == 500
    assert "helm exploded" in created.json()["detail"]
    calls.store_credential.assert_called_once()
    # The row and its credential stay; delete removes both.
    calls.delete_credential.assert_not_called()
    controller.uninstall.assert_awaited_once()
    (new_id,) = _ids(client) - before
    row = _rows(client)[new_id]
    assert row["status"] == "Failed"
    assert "helm exploded" in row["last_error"]
    assert row["last_error_at"]
    controller.install.side_effect = None
    assert (
        client.delete(f"/v1alpha1/vectordb_instances/{new_id}").status_code
        == 204
    )
    calls.delete_credential.assert_called_once()


def test_create_vectordb_instance_store_failure_marks_the_row_failed(
    vectordb_env,
):
    client, controller, calls = vectordb_env
    calls.store_credential.side_effect = RuntimeError("secret write failed")
    before = _ids(client)

    created = _create_vectordb(client)

    assert created.status_code == 500
    controller.install.assert_not_awaited()
    controller.uninstall.assert_not_awaited()
    (new_id,) = _ids(client) - before
    row = _rows(client)[new_id]
    assert row["status"] == "Failed"
    assert "secret write failed" in row["last_error"]
    calls.store_credential.side_effect = None
    assert (
        client.delete(f"/v1alpha1/vectordb_instances/{new_id}").status_code
        == 204
    )


def test_engines_expose_the_cpu_flag():
    app = create_app()
    client = TestClient(app)
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    assert engines["Ollama"]["cpu"] is True
    assert engines["Ollama"]["llm_support"] is True
    assert engines["vLLM"]["cpu"] is False


def test_catalog_contains_the_ollama_demo_models():
    app = create_app()
    client = TestClient(app)
    model_ids = {m["modelId"] for m in client.get("/v1alpha1/models").json()}
    assert {
        "qwen3:0.6b",
        "qwen2.5:1.5b-instruct",
        "smollm2:1.7b",
    } <= model_ids


def test_create_inference_instance_needs_no_hf_token_for_ollama(monkeypatch):
    import api.inference_instance as ii
    from models.inference_instance import DBInferenceInstance

    # Stop before the controller touches a cluster (the pattern of
    # test_create_vectordb_instance_without_cluster_leaves_no_row).
    def boom(*args, **kwargs):
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(ii, "get_controller", boom)
    monkeypatch.delenv("HF_API_TOKEN", raising=False)
    app = create_app()
    client = TestClient(app)
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    models = {m["modelId"]: m for m in client.get("/v1alpha1/models").json()}
    body = {
        "model": {"id": models["qwen3:0.6b"]["id"]},
        "engine": {"id": engines["Ollama"]["id"]},
        "config": {},
    }
    response = client.post("/v1alpha1/inferenceInstance", json=body)
    # Past the token gate: the patched controller fails instead. The row
    # is kept (Failed); its controller keeps failing under this
    # monkeypatch, so clean it up directly rather than through the list
    # endpoint (which would refresh its status and hit the same boom).
    assert response.status_code == 500
    assert "HuggingFace" not in response.json()["detail"]
    db = get_db_direct()
    try:
        row = (
            db.query(DBInferenceInstance)
            .filter(
                DBInferenceInstance.model_id
                == uuid.UUID(models["qwen3:0.6b"]["id"])
            )
            .one()
        )
        assert row.status == "Failed"
        assert "no kubeconfig" in row.last_error
        # The delete route removes both the row and its config; do the
        # same here so no orphan config row is left behind.
        db.delete(row.config)
        db.delete(row)
        db.commit()
    finally:
        db.close()

    body["engine"] = {"id": engines["vLLM"]["id"]}
    response = client.post("/v1alpha1/inferenceInstance", json=body)
    assert response.status_code == 400
    assert "HuggingFace API token" in response.json()["detail"]


def test_ollama_serves_embeddings_too():
    app = create_app()
    client = TestClient(app)
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    assert engines["Ollama"]["embedding_support"] is True
    models = {m["modelId"]: m for m in client.get("/v1alpha1/models").json()}
    assert models["all-minilm:33m"]["category"] == "embedding"


@pytest.fixture
def inference_env(monkeypatch):
    """A mocked controller, credential store and LiteLLM client around
    the inference instance routes."""
    import api.inference_instance as ii
    import api.inference_operations as io
    import api.inference_status as ist

    controller = mock.Mock()
    controller.namespace = "ai-stack"
    controller.get_service_name.return_value = "ollama-abcdef12"
    controller.service_url.return_value = (
        "http://ollama-abcdef12.ai-stack.svc:80"
    )

    async def install(*args, **kwargs):
        return None

    async def uninstall(*args, **kwargs):
        return None

    controller.install = install
    controller.uninstall = uninstall
    # get_controller is called from all three inference modules.
    for module in (ii, io, ist):
        monkeypatch.setattr(
            module, "get_controller", lambda *a, **k: controller
        )
    monkeypatch.setattr(ii, "store_credential", mock.Mock())
    monkeypatch.setattr(ii, "delete_credential", mock.Mock())
    litellm = mock.Mock()
    litellm.register_model.return_value = "mid-42"
    monkeypatch.setattr(ii, "get_litellm_client", lambda: litellm)
    return controller, litellm


def _ollama_body(client):
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    models = {m["modelId"]: m for m in client.get("/v1alpha1/models").json()}
    return {
        "model": {"id": models["qwen3:0.6b"]["id"]},
        "engine": {"id": engines["Ollama"]["id"]},
        "config": {},
    }


def test_create_registers_the_instance_in_litellm(inference_env):
    controller, litellm = inference_env
    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/v1alpha1/inferenceInstance", json=_ollama_body(client)
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert (
        created["litellm_model_name"]
        == f"inst-{created['id'].replace('-', '')[-8:]}"
    )
    # The Ollama chart rows point at the LiteLLM dashboard, filtered on
    # the target name.
    dashboards = client.get(
        f"/v1alpha1/inferenceInstance/{created['id']}/dashboards"
    ).json()
    assert dashboards, "the Ollama llm chart has dashboard rows"
    assert {d["dashboard_id"] for d in dashboards} == {"aiops-litellm"}
    assert all(
        d["query_params"]["var-target"] == created["litellm_model_name"]
        for d in dashboards
    )
    name, params, info = litellm.register_model.call_args.args
    assert name == created["litellm_model_name"]
    assert params["model"] == "openai/qwen3:0.6b"
    assert params["api_base"] == "http://ollama-abcdef12.ai-stack.svc:80/v1"
    assert params["api_key"]  # the workload credential
    assert info == {"mode": "chat", "aiops_instance_id": created["id"]}

    deleted = client.delete(f"/v1alpha1/inferenceInstance/{created['id']}")
    assert deleted.status_code == 200
    litellm.delete_model.assert_called_once_with("mid-42")


def test_create_survives_a_litellm_outage(inference_env):
    controller, litellm = inference_env
    from utils.litellm import LiteLLMError

    litellm.register_model.side_effect = LiteLLMError("down")
    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/v1alpha1/inferenceInstance", json=_ollama_body(client)
    )
    assert response.status_code == 201, response.text
    assert response.json()["litellm_model_name"] is None
    client.delete(f"/v1alpha1/inferenceInstance/{response.json()['id']}")
    litellm.delete_model.assert_not_called()


def test_create_without_litellm_configured(inference_env, monkeypatch):
    import api.inference_instance as ii

    monkeypatch.setattr(ii, "get_litellm_client", lambda: None)
    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/v1alpha1/inferenceInstance", json=_ollama_body(client)
    )
    assert response.status_code == 201, response.text
    assert response.json()["litellm_model_name"] is None
    client.delete(f"/v1alpha1/inferenceInstance/{response.json()['id']}")


# --- Phase 3 Task 1: registry fields, serving options, reference ------------


def _add_model(**overrides) -> str:
    db = get_db_direct()
    try:
        model = DBModel(
            id=genid.uuid4(),
            name=overrides.pop("name", "Registry Test Model"),
            modelId=overrides.pop("modelId", "registry/test-model"),
            category=overrides.pop("category", "llm"),
            **overrides,
        )
        db.add(model)
        db.commit()
        db.refresh(model)
        return str(model.id)
    finally:
        db.close()


def _delete_model(model_id: str):
    db = get_db_direct()
    try:
        mid = uuid.UUID(model_id)
        db.query(ServingOption).filter(ServingOption.model_id == mid).delete()
        db.query(DBModel).filter(DBModel.id == mid).delete()
        db.commit()
    finally:
        db.close()


def _add_serving_option(model_id: str, engine: str, reference: str) -> str:
    db = get_db_direct()
    try:
        option = ServingOption(
            model_id=uuid.UUID(model_id), engine=engine, reference=reference
        )
        db.add(option)
        db.commit()
        db.refresh(option)
        return str(option.id)
    finally:
        db.close()


def _delete_serving_option(option_id: str):
    db = get_db_direct()
    try:
        db.query(ServingOption).filter(
            ServingOption.id == uuid.UUID(option_id)
        ).delete()
        db.commit()
    finally:
        db.close()


def test_catalog_hides_a_draft_row_from_members_shows_it_to_admins(
    oidc_client,  # noqa: F811
    rsa_key,  # noqa: F811
):
    draft_id = _add_model(
        name="Draft Model", modelId="draft/model", status="draft"
    )
    try:
        member = bearer(
            make_token(rsa_key, sub="reg-member", roles=("member",))
        )
        admin = bearer(make_token(rsa_key, sub="reg-admin", roles=("admin",)))

        listed = oidc_client.get("/v1alpha1/models", headers=member).json()
        assert draft_id not in {m["id"] for m in listed}

        member_get = oidc_client.get(
            f"/v1alpha1/models/{draft_id}", headers=member
        )
        assert member_get.status_code == 404

        admin_get = oidc_client.get(
            f"/v1alpha1/models/{draft_id}", headers=admin
        )
        assert admin_get.status_code == 200, admin_get.text
        assert admin_get.json()["status"] == "draft"
    finally:
        _delete_model(draft_id)


def test_model_serving_options_endpoint_shape():
    model_id = _add_model(
        name="Serving Options Model", modelId="org/serving-options"
    )
    option_ids = [
        _add_serving_option(model_id, "HuggingFace", "org/serving-options"),
        # A hosted option has no matching engines row.
        _add_serving_option(model_id, "openrouter", "org/serving-options"),
    ]

    try:
        app = create_app()
        client = TestClient(app)
        response = client.get(f"/v1alpha1/models/{model_id}/serving-options")
        assert response.status_code == 200, response.text
        by_engine = {o["engine"]: o for o in response.json()}
        assert by_engine["HuggingFace"]["engine_id"] is not None
        assert by_engine["HuggingFace"]["cpu"] is False
        assert by_engine["HuggingFace"]["reference"] == "org/serving-options"
        # A hosted option has no engines row: engine_id and cpu are null,
        # and the wizard is expected to skip it.
        assert by_engine["openrouter"]["engine_id"] is None
        assert by_engine["openrouter"]["cpu"] is None
    finally:
        for option_id in option_ids:
            _delete_serving_option(option_id)
        _delete_model(model_id)


def test_create_inference_instance_with_serving_option_persists_reference(
    inference_env,
):
    """A model row of its own (not the seeded qwen3:0.6b, whose own
    Ollama serving option's reference matches its plain modelId) makes
    the GGUF-vs-modelId distinction the register_instance assertion
    below needs unambiguous."""
    controller, litellm = inference_env
    app = create_app()
    client = TestClient(app)
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    model_id = _add_model(
        name="Qwen3 0.6B GGUF", modelId="Qwen/Qwen3-0.6B-GGUF"
    )
    gguf_reference = "hf.co/Qwen/Qwen3-0.6B-GGUF:Q8_0"
    option_id = _add_serving_option(model_id, "Ollama", gguf_reference)

    try:
        response = client.post(
            "/v1alpha1/inferenceInstance",
            json={
                "model": {"id": model_id},
                "engine": {"id": engines["Ollama"]["id"]},
                "config": {},
                "serving_option_id": option_id,
            },
        )
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["reference"] == gguf_reference

        # register_instance (2a) uses the reference, not the catalog's
        # modelId, for the LiteLLM model param.
        name, params, info = litellm.register_model.call_args.args
        assert params["model"] == f"openai/{gguf_reference}"

        deleted = client.delete(f"/v1alpha1/inferenceInstance/{created['id']}")
        assert deleted.status_code == 200
    finally:
        _delete_serving_option(option_id)
        _delete_model(model_id)


def test_create_inference_instance_rejects_a_foreign_serving_option(
    inference_env,
):
    """A serving_option_id must belong to the model it is submitted
    with, not just exist."""
    controller, litellm = inference_env
    app = create_app()
    client = TestClient(app)
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    models = {m["modelId"]: m for m in client.get("/v1alpha1/models").json()}
    other_model_id = _add_model(name="Other Model", modelId="org/other-model")
    option_id = _add_serving_option(other_model_id, "Ollama", "unrelated")

    try:
        response = client.post(
            "/v1alpha1/inferenceInstance",
            json={
                "model": {"id": models["qwen3:0.6b"]["id"]},
                "engine": {"id": engines["Ollama"]["id"]},
                "config": {},
                "serving_option_id": option_id,
            },
        )
        assert response.status_code == 404
    finally:
        _delete_serving_option(option_id)
        _delete_model(other_model_id)
