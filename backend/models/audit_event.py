"""One recorded mutating API call (#14).

The audit middleware (identity stream) writes one row per non-GET
``/v1alpha1/*`` request after the response is produced, with its own
session, and never fails the user's request. ``actor_label`` keeps
the row readable after the user row is gone.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base
from utils import genid


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )
    actor_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # The email, "svc:<azp>", "token:<prefix>" or "anonymous".
    actor_label = Column(String, nullable=False)
    # create, update, delete, reveal, restart, stop, resume, scale,
    # invite, revoke, ...
    action = Column(String, nullable=False)
    # The path segment after /v1alpha1/ (inferenceInstance, notebooks,
    # organizations, tokens, ...).
    resource_kind = Column(String, nullable=False)
    resource_id = Column(String, nullable=True)
    # The HTTP status of the response.
    outcome = Column(Integer, nullable=False)
    request_id = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
