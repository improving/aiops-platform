from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from utils import genid

from .model import ModelSchema


class ModelAdapterSchema(BaseModel):
    id: uuid.UUID | None = Field(default_factory=genid.uuid4_gen())
    base_model: ModelSchema | None = None
    name: str
    path: str | None = None
    hf_id: str | None = None
