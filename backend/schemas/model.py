import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ModelSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    modelId: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    size: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
