import uuid

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID

from .database import Base


class InferenceInstanceDashboards(Base):
    __tablename__ = "inference_instance_dashboards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inference_instance_id = Column(UUID(as_uuid=True),
                                   ForeignKey('inference_instances.id'))
    engine_chart_dashboard_id = Column(
        UUID(as_uuid=True), ForeignKey('engine_chart_dashboards.id'))
    org_id = Column(String)
    query_params = Column(JSON)
