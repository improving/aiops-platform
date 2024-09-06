from pydantic import BaseModel
import uuid
from typing import Optional

class EngineSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    description: Optional[str] = None
    helm_chart_repo: Optional[str] = None
    helm_chart_name: Optional[str] = None

    class Config:
        from_attributes = True