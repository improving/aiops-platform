import uuid
from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict

from schemas.model import ModelSchema


class FinetuneBaseSchema(BaseModel):
    name: str
    params: Dict

    model_config = ConfigDict(from_attributes=True)


class FinetuneCreateSchema(FinetuneBaseSchema):
    pass


class FinetuneUpdateSchema(BaseModel):
    name: Optional[str] = None
    base_model: Optional[ModelSchema] = None
    params: Optional[Dict] = None


class FinetuneSchema(FinetuneBaseSchema):
    id: uuid.UUID
    base_model: Optional[ModelSchema] = None
    status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
