import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from utils import genid


class ModelSchema(BaseModel):
    id: Optional[uuid.UUID] = Field(default_factory=genid.uuid4_gen())
    name: Optional[str] = None
    modelId: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    size: Optional[int] = None
    countAdapters: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)
