from pydantic import BaseModel
import uuid
from typing import Optional

class EngineChartsSchema(BaseModel):
    id: uuid.UUID
    engine: Optional[str] = None
    chart_type: Optional[str] = None
    chart_repo: Optional[str] = None
    chart_name: Optional[str] = None

    class Config:
        from_attributes = True