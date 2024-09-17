import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .engine import EngineSchema
from .model import ModelSchema


class InferenceInstanceConfigParamsSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    maxInputLength: Optional[int] = None
    maxTokens: Optional[int] = None
    maxBatchPrefillTokens: Optional[int] = None
    maxBatchTotalTokens: Optional[int] = None
    quantization: Optional[str] = None
    image: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)
