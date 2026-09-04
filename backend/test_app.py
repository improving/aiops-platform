import json

import pytest
from fastapi.testclient import TestClient

from core import create_app


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
