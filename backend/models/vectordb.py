from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base
from utils import genid


# SQLAlchemy model
class DBVectorDB(Base):
    __tablename__ = "vectordb"

    id = Column(UUID(as_uuid=True),
                primary_key=True,
                default=genid.uuid4_gen())
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    chart_repo = Column(String, nullable=False)
    chart_name = Column(String, nullable=False)
