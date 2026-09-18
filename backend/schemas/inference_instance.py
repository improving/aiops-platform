from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils import genid

from .engine import EngineSchema
from .launch import LaunchProgressSchema
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
    # The in-cluster Service URL, for callers that run inside the cluster
    # and cannot use the gateway host: a nip.io name resolves to 127.0.0.1
    # everywhere, which inside a pod is the pod itself. Computed per
    # request from the engine's chart, never stored. Bypasses the gateway
    # and its API-key policy, so it needs no key (see #36).
    clusterEndpoint: str | None = None
    # True when the workload itself checks the API key, so a caller on
    # clusterEndpoint (which skips the gateway) still needs it.
    workloadChecksApiKey: bool = False
    # Read-only, like the two above: what a not-ready instance waits for.
    launch: LaunchProgressSchema | None = None
    healthEndpoint: str | None = None
    metricsEndpoint: str | None = None
    ready: bool | None = False
    status: str | None = None
    litellm_model_name: str | None = None
    # The serving option's reference (Phase 3), when the instance was
    # launched from one; every consumer reads
    # ``instance.reference or instance.model.modelId``.
    reference: str | None = None
    # Operations (#15, #16): set by the platform, read by the UI.
    last_error: str | None = None
    last_error_at: datetime | None = None
    stopped_at: datetime | None = None
    # Launch resources (#16); the controllers render them into the values.
    replicas: int = 1
    gpu_count: int = 1
    cpu: str | None = None
    memory: str | None = None

    model_config = ConfigDict(from_attributes=True)


# A Kubernetes resource quantity: "4", "500m", "16Gi", "0.5".
QUANTITY_PATTERN = r"^[0-9]+(\.[0-9]+)?(m|[EPTGMK]i?)?$"


class InferenceInstanceCreateSchema(InferenceInstanceSchema):
    """Request body for creating an inference instance.

    ``serving_option_id`` is request-only, like NotebookCreateSchema's
    name validation: it selects one of the model's serving options
    (schemas/serving_option.py) and its ``reference`` is persisted on
    the instance row instead of being echoed back on read.

    The resource bounds live here for the same reason: rows written
    before them must still serialize through InferenceInstanceSchema.
    """

    serving_option_id: uuid.UUID | None = None
    replicas: int = Field(default=1, ge=1, le=16)
    gpu_count: int = Field(default=1, ge=1, le=8)
    cpu: str | None = Field(
        default=None, pattern=QUANTITY_PATTERN, max_length=32
    )
    memory: str | None = Field(
        default=None, pattern=QUANTITY_PATTERN, max_length=32
    )

    @field_validator("cpu", "memory", mode="before")
    @classmethod
    def empty_is_none(cls, value):
        return None if value == "" else value
