import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class InferenceInstanceDashboardsSchema(BaseModel):
    id: uuid.UUID
    dashboard_id: Optional[str] = None
    dashboard_name: Optional[str] = None
    panel_id: Optional[str] = None
    panel_name: Optional[str] = None
    org_id: str
    query_params: dict

    model_config = ConfigDict(from_attributes=True)
