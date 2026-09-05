"""One way to serve a catalog entry: which engine can run it, and the
reference the controller needs (an Ollama tag, a Hugging Face repo, a
``hf.co/<repo>:<quant>`` GGUF pull for Ollama, or a hosted provider
model id such as an OpenRouter id)."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid


class ServingOption(Base):
    __tablename__ = "model_serving_options"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
    )
    engine = Column(String, nullable=False)
    reference = Column(String, nullable=False)
    default_args = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    model = relationship("DBModel", back_populates="serving_options")

    __table_args__ = (
        UniqueConstraint(
            "model_id", "engine", name="uq_serving_options_model_engine"
        ),
    )
