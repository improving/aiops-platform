import uuid

from pydantic import BaseModel


class ServingOptionCreateSchema(BaseModel):
    engine: str
    reference: str
    default_args: dict | None = None


class RegistryEntryPreviewSchema(BaseModel):
    """One ``registry.entry.RegistryEntry`` from a search or a
    preflight fetch, before it becomes a row."""

    source: str
    source_id: str
    name: str
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    size: int | None = None
    license: str | None = None
    parameters: int | None = None
    context_length: int | None = None
    capabilities: list[str] = []
    formats: list[str] = []
    tags: list[str] = []
    serving_options: list[ServingOptionCreateSchema] = []
    already_imported: bool = False


class RegistryImportRequest(BaseModel):
    source: str
    source_id: str
    status: str | None = None
    # Required for source == "openrouter": an enabled OpenRouter
    # provider (Phase 2b) to register the model under, so it becomes a
    # chat target.
    provider_id: uuid.UUID | None = None


class RegistryManualCreateRequest(BaseModel):
    name: str
    model_id: str
    category: str
    subcategory: str | None = None
    description: str | None = None
    size: int | None = None
    license: str | None = None
    serving_options: list[ServingOptionCreateSchema] = []


class RegistryUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    license: str | None = None
    status: str | None = None
    context_length: int | None = None
    capabilities: list[str] | None = None
    serving_options: list[ServingOptionCreateSchema] | None = None
