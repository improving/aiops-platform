from pydantic import BaseModel
import uuid
from typing import Optional

class InferenceInstanceDashboardsSchema(BaseModel):
    id: uuid.UUID
    dashboard_id: Optional[str] = None
    dashboard_name: Optional[str] = None
    panel_id: Optional[str] = None
    panel_name: Optional[str] = None
    org_id: str
    query_params: str

    class Config:
        from_attributes = True