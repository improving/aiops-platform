import uuid

from sqlalchemy import JSON, UUID, Column, ForeignKey, String
from sqlalchemy.orm import relationship

from db.database import Base


# SQLAlchemy model
class DBVectorDBInstance(Base):
    __tablename__ = "vectordb_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vectordb_id = Column(UUID(as_uuid=True), ForeignKey('vectordb.id'))
    configParams = Column(JSON, nullable=True)  # Change this line
    endpoint = Column(String, nullable=True)

    vectorDB = relationship("DBVectorDB")
