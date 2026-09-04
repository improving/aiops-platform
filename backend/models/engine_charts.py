from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base
from utils import genid


class DBEngineCharts(Base):
    __tablename__ = "engine_charts"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    engine = Column(String, nullable=False)
    chart_type = Column(String, nullable=False)
    chart_repo = Column(String, nullable=False)
    chart_name = Column(String, nullable=False)
    chart_version = Column(String, nullable=True)
