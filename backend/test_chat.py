import json
from unittest import mock

import httpx
import pytest
from fastapi.testclient import TestClient

from core import create_app

INSTANCE = "11111111-2222-4333-8444-555555555555"
BODY = {
    "model": "qwen3:0.6b",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": True,
}
SSE = (
    b'data: {"id":"1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"pong"}}]}\n\n'
    b"data: [DONE]\n\n"
)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def mock_upstream(handler):
    """Patch the upstream client with an httpx.MockTransport."""
    return mock.patch(
        "api.chat.upstream_client",
        return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_chat_requires_the_instance_header(client):
    response = client.post("/v1alpha1/chat/completions", json=BODY)
    assert response.status_code == 400
    assert "X-AIOps-Instance" in response.json()["detail"]

    response = client.post(
        "/v1alpha1/chat/completions",
        json=BODY,
        headers={"X-AIOps-Instance": "not-a-uuid"},
    )
    assert response.status_code == 400


def test_chat_unknown_instance_is_404(client):
    response = client.post(
        "/v1alpha1/chat/completions",
        json=BODY,
        headers={"X-AIOps-Instance": INSTANCE},
    )
    assert response.status_code == 404


def test_chat_streams_the_upstream_answer(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, content=SSE, headers={"content-type": "text/event-stream"}
        )

    with (
        mock.patch(
            "api.chat.resolve_target",
            return_value=("https://inf-test.example", "k3y"),
        ),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions",
            json=BODY,
            headers={"X-AIOps-Instance": INSTANCE},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == SSE
    assert seen["url"] == "https://inf-test.example/v1/chat/completions"
    assert seen["key"] == "k3y"
    assert seen["body"]["model"] == "qwen3:0.6b"


def test_chat_returns_json_without_stream(client):
    answer = {
        "choices": [{"message": {"role": "assistant", "content": "pong"}}]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") is None
        return httpx.Response(200, json=answer)

    with (
        mock.patch(
            "api.chat.resolve_target",
            return_value=("http://10.0.0.1:80", None),
        ),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions",
            json={**BODY, "stream": False},
            headers={"X-AIOps-Instance": INSTANCE},
        )
    assert response.status_code == 200
    assert response.json() == answer


def test_chat_forwards_upstream_errors(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    with (
        mock.patch(
            "api.chat.resolve_target",
            return_value=("https://inf-test.example", "k3y"),
        ),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions",
            json=BODY,
            headers={"X-AIOps-Instance": INSTANCE},
        )
    assert response.status_code == 404
    assert "model not found" in response.json()["detail"]


def test_chat_unreachable_upstream_is_502(client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with (
        mock.patch(
            "api.chat.resolve_target",
            return_value=("https://inf-test.example", None),
        ),
        mock_upstream(handler),
    ):
        response = client.post(
            "/v1alpha1/chat/completions",
            json=BODY,
            headers={"X-AIOps-Instance": INSTANCE},
        )
    assert response.status_code == 502


def test_chat_mock_mode_echoes_the_last_user_message(client, monkeypatch):
    monkeypatch.setenv("AIOPS_CHAT_MOCK", "true")
    response = client.post("/v1alpha1/chat/completions", json=BODY)
    assert response.status_code == 200
    # One SSE chunk per word: join the deltas before asserting.
    deltas = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    text = "".join(d["choices"][0]["delta"].get("content", "") for d in deltas)
    assert text.strip() == "You said: hello"
    assert response.text.rstrip().endswith("data: [DONE]")

    response = client.post(
        "/v1alpha1/chat/completions", json={**BODY, "stream": False}
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "You said: hello"
