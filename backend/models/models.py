from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


# SQLAlchemy model
class DBModel(Base):
    __tablename__ = "models"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=genid.uuid4_gen(tag="model"),
    )
    name = Column(String, nullable=False)
    modelId = Column(String, nullable=False)
    description = Column(String)
    category = Column(String)
    subcategory = Column(String)
    size = Column(BigInteger)
    created_at = Column(
        DateTime(timezone=True), default=datetime.now, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    model_adapters = relationship(
        "DBModelAdapters", back_populates="base_model"
    )
