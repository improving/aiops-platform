import json

import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_endpoint():
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
    ])
def test_get_apis(snapshot, name, endpoint):
    response = client.get(endpoint)
    assert response.status_code == 200
    snapshot.assert_match(json.dumps(response.json(), indent=2),
                          f"{name}.json")
