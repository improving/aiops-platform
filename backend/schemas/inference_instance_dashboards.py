import uuid

from pydantic import BaseModel, ConfigDict


class InferenceInstanceDashboardsSchema(BaseModel):
    id: uuid.UUID
    dashboard_id: str | None = None
    dashboard_name: str | None = None
    panel_id: str | None = None
    panel_name: str | None = None
    org_id: str
    query_params: dict

    model_config = ConfigDict(from_attributes=True)
