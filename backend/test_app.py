import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api.inference_instance import missing_endpoint_clause
from core import create_app
from schemas.notebook import NOTEBOOK_NAME_MAX_LENGTH


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
    app = create_app(setup_db=False)
    with TestClient(app) as client:
        scheduler = app.state.scheduler
        assert scheduler.running
        assert len(scheduler.get_jobs()) == 3
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
