from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    # admin, member or viewer.
    role = Column(String, nullable=False)

    user = relationship("User")
    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),
    )
