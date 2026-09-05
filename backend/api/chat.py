"""OpenAI-compatible chat passthrough to one deployed inference instance.

``POST /v1alpha1/chat/completions`` forwards the body unchanged to
``<instance.endpoint>/v1/chat/completions`` with the instance's workload
credential in ``x-api-key`` (the header the gateway's apiKeyAuth reads,
``utils/gateway.py`` APIKEY_HEADERS) and relays the answer, streamed when
the body asks for ``"stream": true``. The instance comes from the
``X-AIOps-Instance`` header, so the ``model`` field stays what the engine
expects (an Ollama tag). Phase 2 routes the same request through LiteLLM.
"""

import json
import os
import uuid
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from auth.current_user import CurrentUser, get_current_user
from auth.policy import authorize_read
from db.database import get_db
from logger import setup_logger
from models.inference_instance import DBInferenceInstance
from utils.credentials import find_credential, read_credential_value

router = APIRouter()
logger = setup_logger(__name__)

INSTANCE_HEADER = "X-AIOps-Instance"
UPSTREAM_PATH = "/v1/chat/completions"
CREDENTIAL_KIND = "inf"
CHAT_MOCK_ENV = "AIOPS_CHAT_MOCK"
# No read timeout: a CPU model streams for a while between tokens.
UPSTREAM_TIMEOUT = httpx.Timeout(
    connect=10.0, read=None, write=30.0, pool=10.0
)
SSE_HEADERS = {"cache-control": "no-cache", "x-accel-buffering": "no"}


def chat_mock_enabled() -> bool:
    """The canned answer for the UI fast tier; needs TEST_MODE like
    AUTH_MODE=disabled does."""
    return (
        os.environ.get(CHAT_MOCK_ENV, "").lower() == "true"
        and os.environ.get("TEST_MODE", "").lower() == "true"
    )


def upstream_client() -> httpx.AsyncClient:
    """One client per request; tests patch this with a MockTransport."""
    return httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT)


def resolve_target(
    db: Session, instance_id: uuid.UUID, user: CurrentUser
) -> tuple[str, str | None]:
    """The instance's base URL and API key, after the read policy."""
    instance = (
        db.query(DBInferenceInstance)
        .filter(DBInferenceInstance.id == instance_id)
        .first()
    )
    if instance is None:
        raise HTTPException(
            status_code=404, detail="Inference instance not found"
        )
    authorize_read(user, instance, "inference instance")
    if not instance.endpoint:
        raise HTTPException(
            status_code=503,
            detail="Inference instance has no endpoint yet",
        )
    credential = find_credential(db, CREDENTIAL_KIND, instance.id)
    api_key = read_credential_value(credential) if credential else None
    return instance.endpoint.rstrip("/"), api_key


def _last_user_text(body: dict) -> str:
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, list):
            return "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        return str(content or "")
    return ""


def _mock_chunk(delta: dict, finish: str | None = None) -> bytes:
    payload = {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "model": "mock",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _mock_response(body: dict):
    reply = f"You said: {_last_user_text(body)}"
    if not body.get("stream"):
        return JSONResponse(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": body.get("model", "mock"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    async def stream() -> AsyncIterator[bytes]:
        yield _mock_chunk({"role": "assistant", "content": ""})
        for word in reply.split(" "):
            yield _mock_chunk({"content": word + " "})
        yield _mock_chunk({}, "stop")
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


def _upstream_error(response: httpx.Response, detail: bytes) -> HTTPException:
    text = detail.decode("utf-8", errors="replace")[:500]
    return HTTPException(
        status_code=response.status_code, detail=f"Upstream error: {text}"
    )


@router.post("/v1alpha1/chat/completions")
async def chat_completions(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    instance_header: str | None = Header(default=None, alias=INSTANCE_HEADER),
):
    body = await request.json()
    if chat_mock_enabled():
        return _mock_response(body)

    if not instance_header:
        raise HTTPException(
            status_code=400, detail=f"{INSTANCE_HEADER} header is required"
        )
    try:
        instance_id = uuid.UUID(instance_header)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{INSTANCE_HEADER} is not a UUID"
        )

    base_url, api_key = resolve_target(db, instance_id, user)
    url = f"{base_url}{UPSTREAM_PATH}"
    headers = {"content-type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    client = upstream_client()
    try:
        if body.get("stream"):
            upstream = await client.send(
                client.build_request("POST", url, json=body, headers=headers),
                stream=True,
            )
        else:
            upstream = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as e:
        await client.aclose()
        logger.warning(f"chat upstream unreachable for {instance_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach the inference instance: {e}",
        )

    if upstream.status_code >= 400:
        detail = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        raise _upstream_error(upstream, detail)

    if not body.get("stream"):
        payload = upstream.json()
        await client.aclose()
        return JSONResponse(payload)

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(), media_type="text/event-stream", headers=SSE_HEADERS
    )
