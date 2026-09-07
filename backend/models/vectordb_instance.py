from sqlalchemy import JSON, UUID, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


# SQLAlchemy model
class DBVectorDBInstance(Base):
    __tablename__ = "vectordb_instances"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    vectordb_id = Column(UUID(as_uuid=True), ForeignKey("vectordb.id"))
    configParams = Column(JSON, nullable=True)  # Change this line
    endpoint = Column(String, nullable=True)
    # The SDK endpoint behind the gateway, API-key protected.
    api_endpoint = Column(String, nullable=True)
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Migration 0008: Pending, Running, Failed or Stopped, written by
    # the platform; NULL means "derive from the pod".
    status = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)

    vectorDB = relationship("DBVectorDB")
