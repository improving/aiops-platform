import uuid

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID

from .database import Base


class DBEngineCharts(Base):
    __tablename__ = "engine_charts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engine = Column(String, nullable=False)
    chart_type = Column(String, nullable=False)
    chart_repo = Column(String, nullable=False)
    chart_name = Column(String, nullable=False)
