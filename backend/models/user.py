from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base
from utils import genid


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    # The OIDC subject claim.
    sub = Column(String, nullable=False)
    email = Column(String, nullable=True)
    name = Column(String, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("sub", name="uq_users_sub"),)
