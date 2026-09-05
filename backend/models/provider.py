from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class Provider(Base):
    """One hosted provider (OpenAI, Anthropic, Gemini, Groq,
    OpenRouter) added by an organization admin. The API key lives in
    the Secret named ``secret_name`` (``utils/secret_store.py``,
    ``utils/providers.py`` ``provider_secret_name``), never in this
    row.
    """

    __tablename__ = "providers"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    kind = Column(String, nullable=False)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=True)
    secret_name = Column(String, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    models = relationship(
        "ProviderModel",
        back_populates="provider",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_providers_org_name"),
    )


class ProviderModel(Base):
    """One model exposed from a provider, registered in LiteLLM as
    ``prov-<id8>/<model>`` (``utils/litellm.py`` ``hosted_model_name``).
    """

    __tablename__ = "provider_models"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    model = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    litellm_model_name = Column(String, nullable=False)
    litellm_model_id = Column(String, nullable=True)
    # "chat" or "embedding".
    capability = Column(String, nullable=False)
    context_length = Column(Integer, nullable=True)
    input_cost_per_token = Column(Numeric(18, 10), nullable=True)
    output_cost_per_token = Column(Numeric(18, 10), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    provider = relationship("Provider", back_populates="models")

    __table_args__ = (
        UniqueConstraint(
            "provider_id", "model", name="uq_provider_models_provider_model"
        ),
    )
