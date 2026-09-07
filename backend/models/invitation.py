"""An email invitation into an organization (#13).

An organization admin creates it with a role; when a user with that
email authenticates, the identity stream creates the membership with
the invitation's role and stamps ``accepted_at`` and
``accepted_user_id``. ``email`` is lowercased on write, so the unique
constraint on (``org_id``, ``email``) is case-insensitive in effect.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    # Lowercased by the writer; the unique constraint relies on it.
    email = Column(String, nullable=False)
    # admin, member or viewer.
    role = Column(String, nullable=False)
    invited_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    accepted_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_invitations_org_email"),
    )
