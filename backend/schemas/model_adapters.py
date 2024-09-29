import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .model import ModelSchema


class ModelAdapterSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    base_model: ModelSchema
    name: str
    path: Optional[str] = None
    hf_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
