import uuid

from sqlalchemy import Boolean, Column, String
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base


# SQLAlchemy model
class DBEngine(Base):
    __tablename__ = "engines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    llm_support = Column(Boolean, nullable=False)
    embedding_support = Column(Boolean, nullable=False)
    reranking_support = Column(Boolean, nullable=False)
    prompt_guard_support = Column(Boolean, nullable=False)
    vector_db_support = Column(Boolean, nullable=False)
