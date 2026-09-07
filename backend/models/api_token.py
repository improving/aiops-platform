"""A personal API token minted by the platform (#18).

The token is ``aiops_<prefix>_<secret>``; only ``prefix`` (8
characters, the lookup key) and the SHA-256 hex digest of ``secret``
are stored, and the full value is shown once at creation. ``scope`` is
``read`` or ``write``; a revoked token keeps its row with
``revoked_at`` set.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name = Column(String, nullable=False)
    # 8 characters; unique across every organization.
    prefix = Column(String, nullable=False)
    # sha256(secret) as hex; never the secret itself.
    token_hash = Column(String, nullable=False)
    # read or write.
    scope = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User")
    organization = relationship("Organization")

    __table_args__ = (UniqueConstraint("prefix", name="uq_api_tokens_prefix"),)
