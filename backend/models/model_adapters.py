import uuid

from sqlalchemy import (CheckConstraint, Column, ForeignKey, String,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base


class DBModelAdapters(Base):
    __tablename__ = "model_adapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    model_id = Column(UUID(as_uuid=True),
                      ForeignKey('models.id'),
                      nullable=False)
    path = Column(String)
    hf_id = Column(String)

    base_model = relationship("DBModel")

    __table_args__ = (
        UniqueConstraint('model_id', 'name', name='uq_model_adapter_name'),
        CheckConstraint('(path IS NOT NULL) OR (hf_id IS NOT NULL)',
                        name='check_path_or_hf_id_not_null'),
    )
