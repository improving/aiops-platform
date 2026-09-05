"""Hosted providers (OpenAI, Anthropic, Gemini, Groq, OpenRouter): an
organization admin adds a provider with an API key, picks the models to
expose, and every exposed model is registered in LiteLLM as
``prov-<id8>/<model>`` (``utils/litellm.py`` ``hosted_model_name``,
``hosted_litellm_params``). Members read providers (without secrets)
and the models they expose; only admins write.

Every write that needs LiteLLM registers or deletes models before it
commits the database row, and rolls the registration and the Secret
back on a ``LiteLLMError`` (502) so nothing is left half-registered.
``AIOPS_CHAT_MOCK=true`` (``api.chat.chat_mock_enabled``) mocks
discovery and registration for the Playwright fast tier, the same as
the rest of the chat surface.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.chat import chat_mock_enabled
from auth.current_user import CurrentUser, get_current_user, require_admin
from auth.policy import authorize_read, org_scope
from db.database import get_db
from logger import setup_logger
from models.provider import Provider, ProviderModel
from schemas.provider import (
    DiscoveredModelSchema,
    ProviderCreateRequest,
    ProviderDiscoverRequest,
    ProviderModelsAddRequest,
    ProviderModelSchema,
    ProviderSchema,
    ProviderUpdateRequest,
)
from utils import genid
from utils.kubernetes_utils import get_default_namespace
from utils.litellm import (
    LiteLLMError,
    hosted_litellm_params,
    hosted_model_name,
)
from utils.litellm import get_client as get_litellm_client
from utils.providers import (
    PROVIDER_KINDS,
    SECRET_KEY,
    DiscoveredModel,
    ProviderError,
    capability_for,
    discover_models,
    enrich,
    provider_secret_name,
)
from utils.secret_store import get_secret_store

router = APIRouter()
logger = setup_logger(__name__)

# The mock discovery result, for AIOPS_CHAT_MOCK (api.chat) and the fast
# Playwright tier: one canned model per capability, for every kind.
MOCK_MODELS = (
    DiscoveredModel(
        id="mock-chat-1",
        display_name="Mock Chat 1",
        context_length=8192,
        capability="chat",
    ),
    DiscoveredModel(
        id="mock-embed-1",
        display_name="Mock Embed 1",
        context_length=None,
        capability="embedding",
    ),
)
MOCK_LITELLM_MODEL_ID = "mock"


def litellm_client():
    """The proxy client, or None when it is not configured. A seam of
    its own (rather than api.chat's) so tests patch this module."""
    return get_litellm_client()


def _require_litellm():
    """None in mock mode; the client otherwise, or a 503 when LiteLLM
    is not configured."""
    if chat_mock_enabled():
        return None
    litellm = litellm_client()
    if litellm is None:
        raise HTTPException(
            status_code=503, detail="LiteLLM is not configured"
        )
    return litellm


def _validate_kind(kind: str) -> None:
    if kind not in PROVIDER_KINDS:
        raise HTTPException(
            status_code=400, detail=f"Unknown provider kind: {kind}"
        )


def _find_provider(db: Session, id: uuid.UUID, user: CurrentUser) -> Provider:
    provider = db.query(Provider).filter(Provider.id == id).first()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    authorize_read(user, provider, "provider")
    return provider


def _provider_response(provider: Provider) -> ProviderSchema:
    return ProviderSchema(
        id=provider.id,
        kind=provider.kind,
        name=provider.name,
        base_url=provider.base_url,
        enabled=provider.enabled,
        has_key=True,
        models=[
            ProviderModelSchema.model_validate(m) for m in provider.models
        ],
    )


def _with_price(kind: str, model: DiscoveredModel) -> DiscoveredModelSchema:
    price = enrich(kind, model.id)
    return DiscoveredModelSchema(
        id=model.id,
        display_name=model.display_name,
        context_length=model.context_length,
        capability=model.capability,
        input_cost_per_token=price.input_cost_per_token if price else None,
        output_cost_per_token=price.output_cost_per_token if price else None,
    )


def _mock_discovered() -> list[DiscoveredModelSchema]:
    return [_with_price("mock", m) for m in MOCK_MODELS]


def _rollback_registrations(litellm, registered: list[tuple]) -> None:
    if litellm is None:
        return
    for entry in registered:
        litellm_model_id = entry[2]
        try:
            litellm.delete_model(litellm_model_id)
        except LiteLLMError as e:
            logger.error(
                "Could not roll back LiteLLM registration %s: %s",
                litellm_model_id,
                e,
            )


def _register(
    litellm,
    provider: Provider,
    model_id: str,
    api_key: str | None,
    base_url: str | None,
) -> tuple[str, str, str, str] | None:
    """(model, litellm_model_name, litellm_model_id, capability), or
    None when the model's mode is not chat or embedding."""
    capability = capability_for(provider.kind, model_id)
    if capability is None:
        return None
    litellm_name = hosted_model_name(provider.id, model_id)
    if litellm is None:
        litellm_model_id = MOCK_LITELLM_MODEL_ID
    else:
        params, info = hosted_litellm_params(
            provider.id, provider.kind, model_id, capability, api_key, base_url
        )
        litellm_model_id = litellm.register_model(litellm_name, params, info)
    return model_id, litellm_name, litellm_model_id, capability


def _add_model_row(
    db: Session,
    provider: Provider,
    registration: tuple,
    display_names: dict[str, str] | None = None,
) -> None:
    model_id, litellm_name, litellm_model_id, capability = registration
    price = enrich(provider.kind, model_id)
    display_name = (display_names or {}).get(model_id) or model_id
    db.add(
        ProviderModel(
            provider_id=provider.id,
            model=model_id,
            display_name=display_name,
            litellm_model_name=litellm_name,
            litellm_model_id=litellm_model_id,
            capability=capability,
            context_length=price.max_input_tokens if price else None,
            input_cost_per_token=price.input_cost_per_token if price else None,
            output_cost_per_token=price.output_cost_per_token
            if price
            else None,
            enabled=True,
        )
    )


@router.post(
    "/v1alpha1/providers/discover",
    response_model=list[DiscoveredModelSchema],
)
async def discover(
    body: ProviderDiscoverRequest,
    user: CurrentUser = Depends(require_admin),
):
    """The preflight the "Add provider" dialog uses before the row
    exists: the provider's models, with the price fields filled in from
    the local catalog."""
    _validate_kind(body.kind)
    if chat_mock_enabled():
        return _mock_discovered()
    try:
        models = await asyncio.to_thread(
            discover_models, body.kind, body.api_key, body.base_url
        )
    except ProviderError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return [_with_price(body.kind, m) for m in models]


@router.get("/v1alpha1/providers", response_model=list[ProviderSchema])
async def list_providers(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    providers = db.query(Provider).filter(org_scope(Provider, user)).all()
    return [_provider_response(p) for p in providers]


@router.post(
    "/v1alpha1/providers", response_model=ProviderSchema, status_code=201
)
async def create_provider(
    body: ProviderCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    _validate_kind(body.kind)
    litellm = _require_litellm()

    provider_id = genid.uuid4()
    provider = Provider(
        id=provider_id,
        org_id=user.org_id,
        kind=body.kind,
        name=body.name,
        base_url=body.base_url,
        secret_name=provider_secret_name(provider_id),
        enabled=True,
    )
    db.add(provider)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Provider '{body.name}' already exists"
        )

    namespace = get_default_namespace()
    store = get_secret_store()
    store.write(namespace, provider.secret_name, {SECRET_KEY: body.api_key})

    registered = []
    try:
        for model_id in body.models:
            registration = _register(
                litellm, provider, model_id, body.api_key, body.base_url
            )
            if registration is not None:
                registered.append(registration)
    except LiteLLMError as e:
        _rollback_registrations(litellm, registered)
        store.delete(namespace, provider.secret_name)
        db.rollback()
        raise HTTPException(status_code=502, detail=str(e))

    for registration in registered:
        _add_model_row(db, provider, registration, body.display_names)
    db.commit()
    db.refresh(provider)
    return _provider_response(provider)


@router.patch("/v1alpha1/providers/{id}", response_model=ProviderSchema)
async def update_provider(
    id: uuid.UUID,
    body: ProviderUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    provider = _find_provider(db, id, user)

    # Plain fields first: a duplicate name fails here, before any Secret
    # or LiteLLM registration is touched.
    if body.name is not None:
        provider.name = body.name
    if body.base_url is not None:
        provider.base_url = body.base_url
    if body.enabled is not None:
        provider.enabled = body.enabled
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Provider '{body.name}' already exists"
        )

    if body.api_key is not None:
        litellm = _require_litellm()
        base_url = (
            body.base_url if body.base_url is not None else provider.base_url
        )
        new_ids: list[tuple[ProviderModel, str]] = []
        try:
            for model in provider.models:
                litellm_name = hosted_model_name(provider.id, model.model)
                if litellm is None:
                    new_id = MOCK_LITELLM_MODEL_ID
                else:
                    params, info = hosted_litellm_params(
                        provider.id,
                        provider.kind,
                        model.model,
                        model.capability,
                        body.api_key,
                        base_url,
                    )
                    new_id = litellm.register_model(litellm_name, params, info)
                new_ids.append((model, new_id))
        except LiteLLMError as e:
            if litellm is not None:
                for _, new_id in new_ids:
                    try:
                        litellm.delete_model(new_id)
                    except LiteLLMError as delete_error:
                        logger.error(
                            "Could not roll back re-registration %s: %s",
                            new_id,
                            delete_error,
                        )
            raise HTTPException(status_code=502, detail=str(e))

        for model, new_id in new_ids:
            old_id = model.litellm_model_id
            model.litellm_model_id = new_id
            if (
                litellm is not None
                and old_id
                and old_id != MOCK_LITELLM_MODEL_ID
            ):
                try:
                    litellm.delete_model(old_id)
                except LiteLLMError as e:
                    logger.error(
                        "Could not delete the old registration %s: %s",
                        old_id,
                        e,
                    )
        store = get_secret_store()
        store.write(
            get_default_namespace(),
            provider.secret_name,
            {SECRET_KEY: body.api_key},
        )

    db.commit()
    db.refresh(provider)
    return _provider_response(provider)


@router.delete("/v1alpha1/providers/{id}")
async def delete_provider(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    provider = _find_provider(db, id, user)
    litellm = None if chat_mock_enabled() else litellm_client()
    if litellm is not None:
        for model in provider.models:
            if not model.litellm_model_id:
                continue
            try:
                litellm.delete_model(model.litellm_model_id)
            except LiteLLMError as e:
                logger.error(
                    "LiteLLM unregistration failed for %s: %s",
                    model.litellm_model_name,
                    e,
                )
    get_secret_store().delete(get_default_namespace(), provider.secret_name)
    db.delete(provider)
    db.commit()
    return {"message": "Provider deleted"}


@router.post(
    "/v1alpha1/providers/{id}/discover",
    response_model=list[DiscoveredModelSchema],
)
async def discover_for_provider(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    provider = _find_provider(db, id, user)
    if chat_mock_enabled():
        return _mock_discovered()
    api_key = get_secret_store().read(
        get_default_namespace(), provider.secret_name, SECRET_KEY
    )
    if api_key is None:
        raise HTTPException(
            status_code=503, detail="The provider's key is not available"
        )
    try:
        models = await asyncio.to_thread(
            discover_models, provider.kind, api_key, provider.base_url
        )
    except ProviderError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return [_with_price(provider.kind, m) for m in models]


@router.post("/v1alpha1/providers/{id}/models", response_model=ProviderSchema)
async def add_provider_models(
    id: uuid.UUID,
    body: ProviderModelsAddRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    provider = _find_provider(db, id, user)
    existing = {m.model for m in provider.models}
    to_add = [m for m in body.models if m not in existing]
    if not to_add:
        return _provider_response(provider)

    litellm = _require_litellm()
    api_key = get_secret_store().read(
        get_default_namespace(), provider.secret_name, SECRET_KEY
    )

    registered = []
    try:
        for model_id in to_add:
            registration = _register(
                litellm, provider, model_id, api_key, provider.base_url
            )
            if registration is not None:
                registered.append(registration)
    except LiteLLMError as e:
        _rollback_registrations(litellm, registered)
        raise HTTPException(status_code=502, detail=str(e))

    for registration in registered:
        _add_model_row(db, provider, registration, body.display_names)
    db.commit()
    db.refresh(provider)
    return _provider_response(provider)


@router.delete("/v1alpha1/providers/{id}/models/{model_id}")
async def delete_provider_model(
    id: uuid.UUID,
    model_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    provider = _find_provider(db, id, user)
    model = next((m for m in provider.models if m.id == model_id), None)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    litellm = None if chat_mock_enabled() else litellm_client()
    if litellm is not None and model.litellm_model_id:
        try:
            litellm.delete_model(model.litellm_model_id)
        except LiteLLMError as e:
            logger.error(
                "LiteLLM unregistration failed for %s: %s",
                model.litellm_model_name,
                e,
            )
    db.delete(model)
    db.commit()
    return {"message": "Model removed"}
