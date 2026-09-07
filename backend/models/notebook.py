from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base
from utils import genid


class Notebook(Base):
    __tablename__ = "notebooks"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    name = Column(String, nullable=False)
    namespace = Column(String, nullable=False)
    type = Column(String, nullable=False)
    framework = Column(String)
    nvidia_gpu = Column(Boolean, nullable=False)
    image = Column(String)
    resources_cpu = Column(String)
    resources_memory = Column(String)
    resources_gpu = Column(String)
    storage_size = Column(String)
    service_type = Column(String)
    service_port = Column(Integer)
    endpoint = Column(String)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
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
