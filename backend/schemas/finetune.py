import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from schemas.model import ModelSchema


class FinetuneBaseSchema(BaseModel):
    name: str
    params: dict

    model_config = ConfigDict(from_attributes=True)


class FinetuneCreateSchema(FinetuneBaseSchema):
    pass


class FinetuneUpdateSchema(BaseModel):
    name: str | None = None
    base_model: ModelSchema | None = None
    params: dict | None = None


class FinetuneSchema(FinetuneBaseSchema):
    id: uuid.UUID
    base_model: ModelSchema | None = None
    status: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
