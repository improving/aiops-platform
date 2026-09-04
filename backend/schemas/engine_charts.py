import uuid

from pydantic import BaseModel, ConfigDict


class EngineChartsSchema(BaseModel):
    id: uuid.UUID
    engine: str | None = None
    chart_type: str | None = None
    chart_repo: str | None = None
    chart_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
