import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from api.database import Base


class Notebook(Base):
    __tablename__ = 'notebooks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
