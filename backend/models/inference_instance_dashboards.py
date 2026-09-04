from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID

from db.database import Base
from utils import genid


class DBInferenceInstanceDashboards(Base):
    __tablename__ = "inference_instance_dashboards"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    inference_instance_id = Column(
        UUID(as_uuid=True), ForeignKey("inference_instances.id")
    )
    engine_chart_dashboard_id = Column(
        UUID(as_uuid=True), ForeignKey("engine_chart_dashboards.id")
    )
    org_id = Column(String)
    query_params = Column(JSON)
