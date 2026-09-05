"""The model registry admins manage (``/v1alpha1/registry``): search a
source, import a preview as a draft or published row, edit metadata
and serving options, sync from the source on demand, and delete. The
published subset is the members' catalog (``api/models.py``
``GET /v1alpha1/models``).

Writes are admin-only; ``GET /`` is open to members but always
filtered to published rows for them. ``AIOPS_CHAT_MOCK=true``
(``api.chat.chat_mock_enabled``) makes ``search``/``fetch`` read the
fixtures under ``test_fixtures/`` instead of the network, the same as
the rest of the chat surface, so the fast Playwright tier can import
``Qwen/Qwen3-0.6B-GGUF`` without hitting Hugging Face.
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.chat import chat_mock_enabled
from api.providers import _add_model_row, _register
from auth.current_user import (
    ROLE_ADMIN,
    CurrentUser,
    get_current_user,
    require_admin,
)
from db.database import get_db
from models.finetune import DBFinetune
from models.inference_instance import DBInferenceInstance
from models.model_adapters import DBModelAdapters
from models.models import STATUS_DRAFT, STATUS_PUBLISHED, DBModel
from models.provider import Provider
from models.serving_option import ServingOption
from paths import BACKEND_DIR
from registry import huggingface as hf_source
from registry import ollama as ollama_source
from registry import openrouter as openrouter_source
from registry import sources
from registry.entry import RegistryEntry, SourceError
from registry.manual import create_manual_model
from registry.sync import apply_sync_fields
from schemas.model import ModelSchema
from schemas.registry import (
    RegistryEntryPreviewSchema,
    RegistryImportRequest,
    RegistryManualCreateRequest,
    RegistryUpdateRequest,
    ServingOptionCreateSchema,
)
from utils import genid
from utils.kubernetes_utils import get_default_namespace
from utils.litellm import LiteLLMError
from utils.litellm import get_client as get_litellm_client
from utils.providers import SECRET_KEY
from utils.secret_store import get_secret_store

router = APIRouter()

FIXTURES_DIR = BACKEND_DIR / "test_fixtures"
# The one entry each mocked source answers with, for the fast
# Playwright tier and AIOPS_CHAT_MOCK backend tests.
_MOCK_HF_FIXTURE = FIXTURES_DIR / "hf_model_qwen3_0_6b_gguf.json"
_MOCK_OLLAMA_FIXTURE = FIXTURES_DIR / "ollama_manifest_qwen3_0_6b.json"
_MOCK_OPENROUTER_FIXTURE = FIXTURES_DIR / "openrouter_models.json"


def _load_fixture(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mock_entries(source: str) -> list[RegistryEntry]:
    if source == "huggingface":
        return [hf_source.parse_model(_load_fixture(_MOCK_HF_FIXTURE))]
    if source == "ollama":
        manifest = _load_fixture(_MOCK_OLLAMA_FIXTURE)
        return [ollama_source.parse_manifest("qwen3", "0.6b", manifest)]
    if source == "openrouter":
        data = _load_fixture(_MOCK_OPENROUTER_FIXTURE)
        return [openrouter_source.parse_model(m) for m in data["data"]]
    return []


def _search_entries(
    source: str, query: str, limit: int
) -> list[RegistryEntry]:
    if chat_mock_enabled():
        return _mock_entries(source)
    try:
        return sources.search(source, query, limit)
    except SourceError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


def _fetch_entry(source: str, source_id: str) -> RegistryEntry:
    if chat_mock_enabled():
        for entry in _mock_entries(source):
            if entry.source_id == source_id:
                return entry
        raise HTTPException(
            status_code=404, detail=f"Unknown entry: {source_id}"
        )
    try:
        return sources.fetch(source, source_id)
    except SourceError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


def _already_imported(db: Session, source: str, source_id: str) -> bool:
    return (
        db.query(DBModel)
        .filter(DBModel.source == source, DBModel.source_id == source_id)
        .first()
        is not None
    )


def _preview(db: Session, entry: RegistryEntry) -> RegistryEntryPreviewSchema:
    return RegistryEntryPreviewSchema(
        source=entry.source,
        source_id=entry.source_id,
        name=entry.name,
        description=entry.description,
        category=entry.category,
        subcategory=entry.subcategory,
        size=entry.size,
        license=entry.license,
        parameters=entry.parameters,
        context_length=entry.context_length,
        capabilities=entry.capabilities,
        formats=entry.formats,
        tags=entry.tags,
        serving_options=[
            ServingOptionCreateSchema(engine=engine, reference=reference)
            for engine, reference in entry.serving_options
        ],
        already_imported=_already_imported(db, entry.source, entry.source_id),
    )


def _model_response(model: DBModel) -> DBModel:
    model.countAdapters = len(model.model_adapters)
    return model


@router.get("/v1alpha1/registry", response_model=list[ModelSchema])
def list_registry(
    status: str | None = None,
    source: str | None = None,
    capability: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Members always see published rows only; an admin may filter by
    ``status`` to see drafts and deprecated entries too."""
    query = db.query(DBModel)
    if user.role == ROLE_ADMIN:
        if status:
            query = query.filter(DBModel.status == status)
    else:
        query = query.filter(DBModel.status == STATUS_PUBLISHED)
    if source:
        query = query.filter(DBModel.source == source)
    if q:
        needle = f"%{q}%"
        query = query.filter(
            or_(DBModel.name.ilike(needle), DBModel.modelId.ilike(needle))
        )
    models = query.all()
    if capability:
        models = [m for m in models if capability in (m.capabilities or [])]
    return [_model_response(m) for m in models]


@router.get(
    "/v1alpha1/registry/search",
    response_model=list[RegistryEntryPreviewSchema],
)
async def search_registry(
    source: str,
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """Previews for the "Import from Hugging Face"/"Add Ollama
    model"/"Add hosted model" dialogs; Ollama has no listing endpoint,
    so ``q`` there is a full ``name:tag`` reference and the answer is
    the one preview its manifest gives."""
    entries = await asyncio.to_thread(_search_entries, source, q, limit)
    return [_preview(db, e) for e in entries]


def _register_openrouter_model(
    db: Session, provider: Provider, entry: RegistryEntry
) -> None:
    """Best-effort mirror of api.providers.add_provider_models for one
    model: registers it in LiteLLM under the provider and adds the
    ProviderModel row, so it becomes a chat target too."""
    litellm = get_litellm_client()
    api_key = get_secret_store().read(
        get_default_namespace(), provider.secret_name, SECRET_KEY
    )
    try:
        registration = _register(
            litellm, provider, entry.source_id, api_key, provider.base_url
        )
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if registration is not None:
        _add_model_row(db, provider, registration)


@router.post(
    "/v1alpha1/registry/import", response_model=ModelSchema, status_code=201
)
async def import_entry(
    body: RegistryImportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    if _already_imported(db, body.source, body.source_id):
        raise HTTPException(
            status_code=409,
            detail=f"{body.source_id} is already imported from {body.source}",
        )

    provider = None
    if body.source == "openrouter":
        if body.provider_id is None:
            raise HTTPException(
                status_code=400,
                detail="provider_id is required for openrouter imports",
            )
        provider = (
            db.query(Provider).filter(Provider.id == body.provider_id).first()
        )
        if (
            provider is None
            or provider.kind != "openrouter"
            or not provider.enabled
        ):
            raise HTTPException(
                status_code=400,
                detail="Unknown or disabled OpenRouter provider",
            )

    entry = await asyncio.to_thread(_fetch_entry, body.source, body.source_id)

    model = DBModel(
        id=genid.uuid4(),
        name=entry.name,
        modelId=entry.source_id,
        description=entry.description,
        category=entry.category,
        subcategory=entry.subcategory,
        size=entry.size,
        source=entry.source,
        source_id=entry.source_id,
        license=entry.license,
        parameters=entry.parameters,
        context_length=entry.context_length,
        capabilities=entry.capabilities,
        formats=entry.formats,
        tags=entry.tags,
        status=body.status or STATUS_DRAFT,
        raw=entry.raw,
    )
    db.add(model)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"{body.source_id} is already imported from {body.source}",
        )

    for engine, reference in entry.serving_options:
        db.add(
            ServingOption(
                model_id=model.id, engine=engine, reference=reference
            )
        )

    if provider is not None:
        _register_openrouter_model(db, provider, entry)

    db.commit()
    db.refresh(model)
    return _model_response(model)


@router.post(
    "/v1alpha1/registry/manual", response_model=ModelSchema, status_code=201
)
def manual_create(
    body: RegistryManualCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    model = create_manual_model(
        db,
        name=body.name,
        model_id=body.model_id,
        category=body.category,
        subcategory=body.subcategory,
        description=body.description,
        size=body.size,
        license=body.license,
        serving_options=[
            (o.engine, o.reference) for o in body.serving_options
        ],
    )
    return _model_response(model)


@router.patch("/v1alpha1/registry/{id}", response_model=ModelSchema)
def update_entry(
    id: uuid.UUID,
    body: RegistryUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    model = db.query(DBModel).filter(DBModel.id == id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    if body.name is not None:
        model.name = body.name
    if body.description is not None:
        model.description = body.description
    if body.license is not None:
        model.license = body.license
    if body.status is not None:
        model.status = body.status
    if body.context_length is not None:
        model.context_length = body.context_length
    if body.capabilities is not None:
        model.capabilities = body.capabilities
    if body.serving_options is not None:
        db.query(ServingOption).filter(ServingOption.model_id == id).delete()
        db.flush()
        for option in body.serving_options:
            db.add(
                ServingOption(
                    model_id=id,
                    engine=option.engine,
                    reference=option.reference,
                    default_args=option.default_args,
                )
            )

    db.commit()
    db.refresh(model)
    return _model_response(model)


@router.post("/v1alpha1/registry/{id}/sync", response_model=ModelSchema)
async def sync_entry(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    model = db.query(DBModel).filter(DBModel.id == id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if not model.source_id:
        raise HTTPException(
            status_code=400, detail="This entry has no source to sync from"
        )

    entry = await asyncio.to_thread(
        _fetch_entry, model.source, model.source_id
    )
    apply_sync_fields(model, entry)
    db.commit()
    db.refresh(model)
    return _model_response(model)


@router.delete("/v1alpha1/registry/{id}")
def delete_entry(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    model = db.query(DBModel).filter(DBModel.id == id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    blockers = []
    if (
        db.query(DBInferenceInstance)
        .filter(DBInferenceInstance.model_id == id)
        .count()
    ):
        blockers.append("inference instances")
    if (
        db.query(DBModelAdapters)
        .filter(DBModelAdapters.model_id == id)
        .count()
    ):
        blockers.append("model adapters")
    if db.query(DBFinetune).filter(DBFinetune.model_id == id).count():
        blockers.append("fine-tune jobs")
    if blockers:
        raise HTTPException(
            status_code=409,
            detail=f"Model is still in use by {', '.join(blockers)}",
        )

    db.delete(model)
    db.commit()
    return {"message": "Model deleted"}
