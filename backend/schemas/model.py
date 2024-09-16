import uuid
from typing import Optional

from pydantic import BaseModel


class ModelSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    modelId: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    size: Optional[int] = None

    class Config:
        from_attributes = True
