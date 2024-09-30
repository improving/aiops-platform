from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from .model import ModelSchema


class ModelAdapterSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    base_model: Optional[ModelSchema] = None
    name: str
    path: Optional[str] = None
    hf_id: Optional[str] = None
