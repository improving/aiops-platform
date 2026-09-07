"""GET /v1alpha1/config/ui: the runtime UI configuration (packaging plan, Task 1)."""

from fastapi.testclient import TestClient

from core import create_app

UI_CONFIG = "/v1alpha1/config/ui"
URL_VARS = ("GRAFANA_URL", "LANGFLOW_URL", "JAEGER_URL")


def test_ui_config_is_empty_without_the_variables(monkeypatch):
    for name in URL_VARS:
        monkeypatch.delenv(name, raising=False)
    client = TestClient(create_app())
    response = client.get(UI_CONFIG)
    assert response.status_code == 200
    assert response.json() == {
        "grafanaUrl": "",
        "langflowUrl": "",
        "jaegerUrl": "",
        "authMode": "disabled",
    }


def test_ui_config_reads_the_environment(monkeypatch):
    monkeypatch.setenv("GRAFANA_URL", " https://grafana.example.test/ ")
    monkeypatch.setenv("LANGFLOW_URL", "https://langflow.example.test")
    monkeypatch.setenv("JAEGER_URL", "https://jaeger.example.test/")
    client = TestClient(create_app())
    assert client.get(UI_CONFIG).json() == {
        "grafanaUrl": "https://grafana.example.test",
        "langflowUrl": "https://langflow.example.test",
        "jaegerUrl": "https://jaeger.example.test",
        "authMode": "disabled",
    }


def test_ui_config_needs_no_token(oidc_client):  # noqa: F811
    response = oidc_client.get(UI_CONFIG)
    assert response.status_code == 200
    assert response.json()["authMode"] == "oidc"
