from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from utils import genid

from .engine import EngineSchema
from .model import ModelSchema


class ModelAdapterReferenceSchema(BaseModel):
    id: uuid.UUID
    name: str | None = None
    path: str | None = None
    hf_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InferenceInstanceConfigParamsSchema(BaseModel):
    id: uuid.UUID | None = Field(default_factory=genid.uuid4_gen())
    maxInputLength: int | None = None
    maxTokens: int | None = None
    maxBatchPrefillTokens: int | None = None
    maxBatchTotalTokens: int | None = None
    quantization: str | None = None
    image: str | None = None
    env_vars: dict[str, str] | None = None
    args: dict[str, str] | None = None
    lora_adapters: list[ModelAdapterReferenceSchema] = []
    enable_tracing: bool | None = False

    model_config = ConfigDict(from_attributes=True)


class InferenceInstanceSchema(BaseModel):
    id: uuid.UUID | None = Field(default_factory=genid.uuid4_gen())
    model: ModelSchema
    engine: EngineSchema
    host: str | None = None
    config: InferenceInstanceConfigParamsSchema | None = None
    endpoint: str | None = None
    healthEndpoint: str | None = None
    metricsEndpoint: str | None = None
    ready: bool | None = False
    status: str | None = None
    litellm_model_name: str | None = None
    # The serving option's reference (Phase 3), when the instance was
    # launched from one; every consumer reads
    # ``instance.reference or instance.model.modelId``.
    reference: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InferenceInstanceCreateSchema(InferenceInstanceSchema):
    """Request body for creating an inference instance.

    ``serving_option_id`` is request-only, like NotebookCreateSchema's
    name validation: it selects one of the model's serving options
    (schemas/serving_option.py) and its ``reference`` is persisted on
    the instance row instead of being echoed back on read.
    """

    serving_option_id: uuid.UUID | None = None
