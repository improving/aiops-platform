import uuid

from pydantic import BaseModel, ConfigDict


class VectorDBSchema(BaseModel):
    id: uuid.UUID
    name: str | None = None
    description: str | None = None
    chart_repo: str | None = None
    chart_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
