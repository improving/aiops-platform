from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from utils import genid

from .engine import EngineSchema
from .model import ModelSchema


class ModelAdapterReferenceSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    path: Optional[str] = None
    hf_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class InferenceInstanceConfigParamsSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=genid.uuid4_gen())
    maxInputLength: Optional[int] = None
    maxTokens: Optional[int] = None
    maxBatchPrefillTokens: Optional[int] = None
    maxBatchTotalTokens: Optional[int] = None
    quantization: Optional[str] = None
    image: Optional[str] = None
    env_vars: Optional[dict[str, str]] = None
    args: Optional[dict[str, str]] = None
    lora_adapters: List[ModelAdapterReferenceSchema] = []
    enable_tracing: Optional[bool] = False

    model_config = ConfigDict(from_attributes=True)


class InferenceInstanceSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=genid.uuid4_gen())
    model: ModelSchema
    engine: EngineSchema
    host: Optional[str] = None
    config: Optional[InferenceInstanceConfigParamsSchema] = None
    endpoint: Optional[str] = None
    healthEndpoint: Optional[str] = None
    metricsEndpoint: Optional[str] = None
    ready: Optional[bool] = False
    status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
