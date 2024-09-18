import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class VectorDBSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    description: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)
