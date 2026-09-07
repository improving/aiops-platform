"""Chat, embeddings and rerank for one deployed inference instance
(``inst-<id8>``) or one hosted provider model (``prov-<id8>/<model>``,
Phase 2b).

``POST /v1alpha1/chat/completions``, ``/v1alpha1/embeddings`` and
``/v1alpha1/rerank`` resolve the target after the read policy and, when
the target is registered in LiteLLM, forward to the proxy with the
caller's organization virtual key (``utils/litellm.py``). Without
LiteLLM, chat falls back to the Phase 1 direct passthrough to the
instance's gateway host with its workload credential in ``x-api-key``
(hosted models have no direct route: they answer 503); embeddings and
rerank answer 503 without LiteLLM regardless of target, since there is
no direct route for them either. ``AIOPS_CHAT_MOCK=true`` (only with
``TEST_MODE=true``) serves a canned target and answers without any
instance, for the Playwright fast tier.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from kubernetes.client.exceptions import ApiException
from sqlalchemy.orm import Session, joinedload, selectinload
from starlette.concurrency import iterate_in_threadpool

from api.inference_status import check_pod_status_and_readiness
from auth.current_user import CurrentUser, get_current_user
from auth.policy import authorize_read, org_scope
from db.database import get_db
from logger import setup_logger
from models.inference_instance import DBInferenceInstance
from models.organization import Organization
from models.provider import Provider
from utils.credentials import find_credential, read_credential_value
from utils.ids import find_by_id8
from utils.litellm import (
    LiteLLMError,
    ensure_org_key,
    get_client,
    instance_model_name,
)

router = APIRouter()
logger = setup_logger(__name__)

UPSTREAM_PATH = "/v1/chat/completions"
CREDENTIAL_KIND = "inf"
CHAT_MOCK_ENV = "AIOPS_CHAT_MOCK"
TARGET_PREFIX = "inst-"
HOSTED_PREFIX = "prov-"
MOCK_TARGET = "inst-mock"
CAPABILITY_BY_CATEGORY = {
    "llm": "chat",
    "embedding": "embedding",
    "reranker": "rerank",
}
# No read timeout: a CPU model streams for a while between tokens.
UPSTREAM_TIMEOUT = httpx.Timeout(
    connect=10.0, read=None, write=30.0, pool=10.0
)
SSE_HEADERS = {"cache-control": "no-cache", "x-accel-buffering": "no"}
SSE_DONE = b"data: [DONE]\n\n"


def _sse_frame(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


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


@dataclass(frozen=True)
class Target:
    """What a route needs to forward, whether the target is a deployed
    instance or a hosted provider model. ``endpoint``/``upstream_model``
    are None for a hosted model, which has no Phase 1 direct route."""

    kind: str  # "instance" or "hosted"
    org_id: uuid.UUID | None
    litellm_model_id: str | None
    endpoint: str | None
    upstream_model: str | None
    api_key_lookup: Callable[[], str | None] | None


def _unknown_target(name: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown target {name}")


def _find_instance_target(db: Session, name: str, user: CurrentUser) -> Target:
    if len(name) != len(TARGET_PREFIX) + 8:
        raise _unknown_target(name)
    instance = find_by_id8(db, DBInferenceInstance, name[len(TARGET_PREFIX) :])
    if instance is None:
        raise _unknown_target(name)
    authorize_read(user, instance, "inference instance")
    return Target(
        kind="instance",
        org_id=instance.org_id,
        litellm_model_id=instance.litellm_model_id,
        endpoint=instance.endpoint,
        upstream_model=instance.reference or instance.model.modelId,
        api_key_lookup=lambda: instance_api_key(db, instance),
    )


def _find_hosted_target(db: Session, name: str, user: CurrentUser) -> Target:
    # "prov-<id8>/<model>"; the model id may itself contain "/"
    # (OpenRouter), so only the first "/" after the id8 is a separator.
    id8_value, sep, _ = name[len(HOSTED_PREFIX) :].partition("/")
    if not sep or not id8_value:
        raise _unknown_target(name)
    provider = find_by_id8(db, Provider, id8_value)
    if provider is None:
        raise _unknown_target(name)
    authorize_read(user, provider, "provider")
    model = next(
        (m for m in provider.models if m.litellm_model_name == name),
        None,
    )
    if model is None or not model.enabled or not provider.enabled:
        raise _unknown_target(name)
    return Target(
        kind="hosted",
        org_id=provider.org_id,
        litellm_model_id=model.litellm_model_id,
        endpoint=None,
        upstream_model=None,
        api_key_lookup=None,
    )


def find_target(db: Session, name: str, user: CurrentUser) -> Target:
    """The target behind ``inst-<id8>`` or ``prov-<id8>/<model>``, after
    the read policy."""
    if name.startswith(TARGET_PREFIX):
        return _find_instance_target(db, name, user)
    if name.startswith(HOSTED_PREFIX):
        return _find_hosted_target(db, name, user)
    raise _unknown_target(name)


def user_key(user: CurrentUser) -> str:
    """The identity LiteLLM records as the end user of a request: the
    platform user id, an opaque value that is stable across email
    changes and never puts an email into LiteLLM's database, its
    metrics labels or an upstream provider's request. The usage
    endpoint maps it back to the email when it builds its response."""
    return str(user.id)


def litellm_client():
    return get_client()


def org_key(db: Session, user: CurrentUser) -> str:
    org = db.query(Organization).filter(Organization.id == user.org_id).first()
    return ensure_org_key(db, org)


def instance_api_key(db: Session, instance) -> str | None:
    credential = find_credential(db, CREDENTIAL_KIND, instance.id)
    return read_credential_value(credential) if credential else None


def list_instance_targets(db: Session, user: CurrentUser) -> list[dict]:
    """The deployed-instance chat/embedding/rerank targets of the
    caller's organization."""
    rows = (
        db.query(DBInferenceInstance)
        .filter(org_scope(DBInferenceInstance, user))
        .all()
    )
    targets = []
    for row in rows:
        registered = bool(row.litellm_model_name)
        if not registered and not (
            row.endpoint and row.model.category == "llm"
        ):
            continue
        try:
            ready, _ = check_pod_status_and_readiness(row, db)
        except Exception:
            ready = False
        targets.append(
            {
                "name": row.litellm_model_name or instance_model_name(row.id),
                "label": f"{row.model.name} · {row.engine.name}",
                "capability": CAPABILITY_BY_CATEGORY.get(
                    row.model.category, "chat"
                ),
                "instance_id": str(row.id),
                "provider_id": None,
                "model": row.reference or row.model.modelId,
                "engine": row.engine.name,
                "ready": bool(ready),
                "via": "litellm" if registered else "direct",
            }
        )
    return targets


def list_hosted_targets(db: Session, user: CurrentUser) -> list[dict]:
    """The hosted-provider chat/embedding targets of the caller's
    organization: every enabled model of every enabled provider."""
    providers = (
        db.query(Provider)
        .filter(org_scope(Provider, user), Provider.enabled.is_(True))
        .all()
    )
    targets = []
    for provider in providers:
        for model in provider.models:
            if not model.enabled:
                continue
            targets.append(
                {
                    "name": model.litellm_model_name,
                    "label": f"{model.display_name} · {provider.name}",
                    "capability": model.capability,
                    "instance_id": None,
                    "provider_id": str(provider.id),
                    "model": model.model,
                    "engine": provider.kind,
                    "ready": True,
                    "via": "litellm",
                }
            )
    return targets


def target_labels(db: Session, user: CurrentUser) -> dict[str, str]:
    """Every target name the caller's organization has ever been able
    to spend on, mapped to its display label, for the usage endpoint.
    Unlike ``list_targets`` this never calls the cluster (no readiness
    check) and keeps disabled provider models, which may still carry
    historical spend."""
    labels: dict[str, str] = {}
    instances = (
        db.query(DBInferenceInstance)
        .options(
            joinedload(DBInferenceInstance.model),
            joinedload(DBInferenceInstance.engine),
        )
        .filter(org_scope(DBInferenceInstance, user))
        .all()
    )
    for row in instances:
        name = row.litellm_model_name or instance_model_name(row.id)
        labels[name] = f"{row.model.name} · {row.engine.name}"
    providers = (
        db.query(Provider)
        .options(selectinload(Provider.models))
        .filter(org_scope(Provider, user))
        .all()
    )
    for provider in providers:
        for model in provider.models:
            labels[model.litellm_model_name] = (
                f"{model.display_name} · {provider.name}"
            )
    return labels


def list_targets(db: Session, user: CurrentUser) -> list[dict]:
    """Every chat/embedding/rerank target of the caller's organization:
    deployed instances, then hosted provider models."""
    return list_instance_targets(db, user) + list_hosted_targets(db, user)


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


def _mock_chat(body: dict):
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


def _mock_embeddings(body: dict):
    inputs = body.get("input")
    inputs = inputs if isinstance(inputs, list) else [inputs]
    return JSONResponse(
        {
            "object": "list",
            "model": body.get("model", "mock"),
            "data": [
                {
                    "object": "embedding",
                    "index": i,
                    "embedding": [0.1, 0.2, 0.3, 0.4],
                }
                for i, _ in enumerate(inputs)
            ],
            "usage": {
                "prompt_tokens": len(inputs),
                "total_tokens": len(inputs),
            },
        }
    )


def _mock_rerank(body: dict):
    documents = body.get("documents") or []
    results = [
        {"index": i, "relevance_score": round(0.1 * (i + 1), 2)}
        for i in reversed(range(len(documents)))
    ]
    return JSONResponse({"id": "rerank-mock", "results": results})


def _stream_error_chunk(message: str) -> bytes:
    """An OpenAI-style error event for a stream that broke after the
    200 went out; the AI SDK turns it into a visible error. It starts on
    a fresh line so a cut half-way through an event cannot swallow it."""
    payload = {"error": {"message": message, "type": "stream_error"}}
    return b"\n\n" + _sse_frame(payload) + SSE_DONE


async def _relay_until_broken(
    chunks: AsyncIterator[bytes], source: str
) -> AsyncIterator[bytes]:
    """Relay the upstream SSE bytes; when the stream breaks after the
    200 went out, end it with an error event instead of a cut body."""
    try:
        async for chunk in chunks:
            yield chunk
    except httpx.HTTPError as e:
        logger.warning(f"chat stream from {source} broke: {e}")
        yield _stream_error_chunk(
            f"The answer stream was interrupted "
            f"({e.__class__.__name__}: {e}). Try again."
        )


def _upstream_error(response: httpx.Response, detail: bytes) -> HTTPException:
    text = detail.decode("utf-8", errors="replace")[:500]
    return HTTPException(
        status_code=response.status_code, detail=f"Upstream error: {text}"
    )


async def _relay_direct(url: str, body: dict, api_key: str | None):
    """The Phase 1 passthrough: the instance's gateway host with x-api-key."""
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
        logger.warning(f"chat upstream unreachable for {url}: {e}")
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
            async for chunk in _relay_until_broken(
                upstream.aiter_bytes(), "the instance"
            ):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(), media_type="text/event-stream", headers=SSE_HEADERS
    )


async def _relay_litellm(litellm, path: str, body: dict, key: str):
    stream = bool(body.get("stream"))
    try:
        response = await asyncio.to_thread(
            litellm.request,
            "POST",
            path,
            json=body,
            stream=stream,
            api_key=key,
        )
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not stream:
        return JSONResponse(response.json())
    if response.status_code >= 400:
        detail = response.read().decode("utf-8", errors="replace")[:500]
        response.close()
        response.extensions["aiops_client"].close()
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Upstream error: {detail}",
        )

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in _relay_until_broken(
                iterate_in_threadpool(response.iter_bytes()), "LiteLLM"
            ):
                yield chunk
        finally:
            response.close()
            response.extensions["aiops_client"].close()

    return StreamingResponse(
        relay(), media_type="text/event-stream", headers=SSE_HEADERS
    )


def _org_key_or_error(db: Session, user: CurrentUser) -> str:
    try:
        return org_key(db, user)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ApiException as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot read the organization key: {e.reason}",
        )


async def _forward(
    db: Session,
    user: CurrentUser,
    body: dict,
    path: str,
    *,
    allow_direct: bool,
):
    name = str(body.get("model") or "")
    target = find_target(db, name, user)
    litellm = litellm_client()
    if litellm is not None and target.litellm_model_id:
        key = await asyncio.to_thread(_org_key_or_error, db, user)
        body = {**body, "user": user_key(user)}
        return await _relay_litellm(litellm, path, body, key)
    if not allow_direct:
        raise HTTPException(
            status_code=503, detail="LiteLLM is not configured"
        )
    if not target.endpoint:
        detail = (
            "Hosted models need LiteLLM"
            if target.kind == "hosted"
            else "Inference instance has no endpoint yet"
        )
        raise HTTPException(status_code=503, detail=detail)
    api_key = target.api_key_lookup() if target.api_key_lookup else None
    return await _relay_direct(
        target.endpoint.rstrip("/") + UPSTREAM_PATH,
        {**body, "model": target.upstream_model},
        api_key,
    )


@router.get("/v1alpha1/chat/targets")
async def chat_targets(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if chat_mock_enabled():
        mock_target = {
            "name": MOCK_TARGET,
            "label": "Mock model · Mock",
            "capability": "chat",
            "instance_id": None,
            "provider_id": None,
            "model": "mock",
            "engine": "Mock",
            "ready": True,
            "via": "mock",
        }
        hosted = await asyncio.to_thread(list_hosted_targets, db, user)
        return [mock_target] + hosted
    return await asyncio.to_thread(list_targets, db, user)


@router.post("/v1alpha1/chat/completions")
async def chat_completions(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    body = await request.json()
    if chat_mock_enabled():
        return _mock_chat(body)
    return await _forward(
        db, user, body, "/v1/chat/completions", allow_direct=True
    )


@router.post("/v1alpha1/embeddings")
async def embeddings(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    body = await request.json()
    if chat_mock_enabled():
        return _mock_embeddings(body)
    return await _forward(db, user, body, "/v1/embeddings", allow_direct=False)


@router.post("/v1alpha1/rerank")
async def rerank(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    body = await request.json()
    if chat_mock_enabled():
        return _mock_rerank(body)
    return await _forward(db, user, body, "/rerank", allow_direct=False)
