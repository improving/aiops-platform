from datetime import datetime

from sqlalchemy import Column, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base
from utils import genid

# The organization every pre-tenancy row was moved into.
DEFAULT_ORG_SLUG = "default"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    slug = Column(String, nullable=False)
    name = Column(String, nullable=False)
    # The organization's id at the identity provider, when it has one.
    idp_org_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    # Per-organization LiteLLM team and the Secret holding its virtual key.
    litellm_team_id = Column(String, nullable=True)
    litellm_key_secret_name = Column(String, nullable=True)
    # Monthly budget in USD for hosted providers; NULL means unlimited.
    budget_usd = Column(Numeric(12, 2), nullable=True)

    __table_args__ = (UniqueConstraint("slug", name="uq_organizations_slug"),)
