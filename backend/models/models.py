import uuid

from sqlalchemy import BigInteger, Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base


# SQLAlchemy model
class DBModel(Base):
    __tablename__ = "models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    modelId = Column(String, nullable=False)
    description = Column(String)
    category = Column(String)
    subcategory = Column(String)
    size = Column(BigInteger)

    model_adapters = relationship("DBModelAdapters",
                                  back_populates="base_model")
