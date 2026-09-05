from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid

# The registry entry's status: only "published" rows are the members'
# catalog (api/models.py); drafts and deprecated entries are managed on
# the admin registry (Phase 3 Task 4).
STATUS_PUBLISHED = "published"
STATUS_DRAFT = "draft"
STATUS_DEPRECATED = "deprecated"


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

    # Registry fields (Phase 3): where the entry came from, and the
    # metadata an importer or a manual edit fills in.
    source = Column(String, nullable=False, server_default="manual")
    source_id = Column(String, nullable=True)
    license = Column(String, nullable=True)
    parameters = Column(BigInteger, nullable=True)
    context_length = Column(Integer, nullable=True)
    capabilities = Column(JSON, nullable=False, server_default="[]")
    formats = Column(JSON, nullable=False, server_default="[]")
    tags = Column(JSON, nullable=False, server_default="[]")
    status = Column(String, nullable=False, server_default=STATUS_PUBLISHED)
    synced_at = Column(DateTime, nullable=True)
    sync_error = Column(String, nullable=True)
    raw = Column(JSON, nullable=True)
    # NULL means a global catalog entry, visible to every organization
    # (api/models.py filters on this, not auth.policy.org_scope, which
    # maps NULL to the default organization only).
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )

    model_adapters = relationship(
        "DBModelAdapters", back_populates="base_model"
    )
    serving_options = relationship(
        "ServingOption",
        back_populates="model",
        cascade="all, delete-orphan",
    )
