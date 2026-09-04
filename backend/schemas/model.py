import uuid

from pydantic import BaseModel, ConfigDict, Field

from utils import genid


class ModelSchema(BaseModel):
    id: uuid.UUID | None = Field(default_factory=genid.uuid4_gen())
    name: str | None = None
    modelId: str | None = None
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    size: int | None = None
    countAdapters: int | None = 0

    model_config = ConfigDict(from_attributes=True)
