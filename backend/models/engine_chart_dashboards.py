import uuid

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base


class DBEngineChartDashboards(Base):
    __tablename__ = "engine_chart_dashboards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dashboard_id = Column(String)
    dashboard_name = Column(String)
    engine_id = Column(UUID(as_uuid=True), ForeignKey('engines.id'))
    engine_chart_id = Column(UUID(as_uuid=True),
                             ForeignKey('engine_charts.id'))
    panel_id = Column(String)
    panel_name = Column(String)
