from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class DBEngineDefaultConfig(Base):
    __tablename__ = "engine_default_configs"

    id = Column(UUID(as_uuid=True),
                primary_key=True,
                default=genid.uuid4_gen())
    engine_id = Column(UUID(as_uuid=True),
                       ForeignKey('engines.id'),
                       nullable=False)
    chart_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    defaultValue = Column(String, nullable=False)
    editable = Column(Boolean, nullable=False, default=False)


class DBEngineDefaultArgs(Base):
    __tablename__ = "engine_default_args"

    id = Column(UUID(as_uuid=True),
                primary_key=True,
                default=genid.uuid4_gen())
    engine_id = Column(UUID(as_uuid=True),
                       ForeignKey('engines.id'),
                       nullable=False)
    chart_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    defaultValue = Column(String, nullable=False)
    editable = Column(Boolean, nullable=False, default=False)


# SQLAlchemy model
class DBEngine(Base):
    __tablename__ = "engines"

    id = Column(UUID(as_uuid=True),
                primary_key=True,
                default=genid.uuid4_gen())
    name = Column(String, nullable=False)
    llm_support = Column(Boolean, nullable=False)
    embedding_support = Column(Boolean, nullable=False)
    reranking_support = Column(Boolean, nullable=False)
    prompt_guard_support = Column(Boolean, nullable=False)
    vector_db_support = Column(Boolean, nullable=False)

    default_config = relationship("DBEngineDefaultConfig")
    default_args = relationship("DBEngineDefaultArgs")
