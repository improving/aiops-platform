import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EngineChartsSchema(BaseModel):
    id: uuid.UUID
    engine: Optional[str] = None
    chart_type: Optional[str] = None
    chart_repo: Optional[str] = None
    chart_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
