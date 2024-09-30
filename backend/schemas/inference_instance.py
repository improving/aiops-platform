from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel, Field

from .engine import EngineSchema
from .model import ModelSchema


class ModelAdapterReferenceSchema(BaseModel):
    id: uuid.UUID
    name: str


class InferenceInstanceConfigParamsSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    maxInputLength: Optional[int] = None
    maxTokens: Optional[int] = None
    maxBatchPrefillTokens: Optional[int] = None
    maxBatchTotalTokens: Optional[int] = None
    quantization: Optional[str] = None
    image: Optional[str] = None
    lora_adapters: List[ModelAdapterReferenceSchema] = []


class InferenceInstanceSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    model: ModelSchema
    engine: EngineSchema
    host: str
    config: Optional[InferenceInstanceConfigParamsSchema] = None
    endpoint: Optional[str] = None
    healthEndpoint: Optional[str] = None
    metricsEndpoint: Optional[str] = None
    ready: Optional[bool] = False
    status: Optional[str] = None
