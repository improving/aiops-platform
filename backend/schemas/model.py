import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from utils import genid

from .serving_option import ServingOptionSchema


class ModelSchema(BaseModel):
    id: uuid.UUID | None = Field(default_factory=genid.uuid4_gen())
    name: str | None = None
    modelId: str | None = None
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    size: int | None = None
    countAdapters: int | None = 0

    # Registry fields (Phase 3), all additive and optional so the launch
    # wizard, the fine-tune flow and pre-registry rows keep working.
    source: str | None = "manual"
    source_id: str | None = None
    license: str | None = None
    parameters: int | None = None
    context_length: int | None = None
    # Default to [], not None: the models.capabilities/formats/tags
    # columns are NOT NULL, and the ORM sends whatever the schema
    # defaults to on a plain POST /v1alpha1/models that omits them.
    capabilities: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: str | None = "published"
    synced_at: datetime | None = None
    sync_error: str | None = None
    raw: dict | None = None
    serving_options: list[ServingOptionSchema] | None = None

    model_config = ConfigDict(from_attributes=True)
