import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base


class DBFinetune(Base):
    __tablename__ = "finetunes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    model_id = Column(UUID(as_uuid=True),
                      ForeignKey('models.id'),
                      nullable=False)
    params = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True),
                        default=datetime.now,
                        nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        default=datetime.now,
                        onupdate=datetime.now,
                        nullable=False)

    base_model = relationship("DBModel")
