from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.database import Base
from utils import genid

# Define the association table
DBInferenceInstanceModelAdapters = Table(
    "inference_instance_model_adapters",
    Base.metadata,
    Column(
        "config_id",
        UUID(as_uuid=True),
        ForeignKey("inference_instance_config_params.id"),
    ),
    Column(
        "model_adapter_id", UUID(as_uuid=True), ForeignKey("model_adapters.id")
    ),
)


# SQLAlchemy models
class DBInferenceInstanceConfigParams(Base):
    __tablename__ = "inference_instance_config_params"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4, index=True
    )
    maxInputLength = Column(Integer)
    maxTokens = Column(Integer)
    maxBatchPrefillTokens = Column(Integer)
    maxBatchTotalTokens = Column(Integer)
    quantization = Column(String)
    image = Column(String)
    env_vars = Column(JSON)
    args = Column(JSON)
    enable_tracing = Column(Boolean)

    # Define the many-to-many relationship
    lora_adapters = relationship(
        "DBModelAdapters",
        secondary=DBInferenceInstanceModelAdapters,
        back_populates="inference_instance_config_params",
    )


class DBInferenceInstance(Base):
    __tablename__ = "inference_instances"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    model_id = Column(UUID(as_uuid=True), ForeignKey("models.id"))
    engine_id = Column(UUID(as_uuid=True), ForeignKey("engines.id"))
    host = Column(String)
    endpoint = Column(String)
    healthEndpoint = Column(String)
    metricsEndpoint = Column(String)
    config_id = Column(
        UUID(as_uuid=True), ForeignKey("inference_instance_config_params.id")
    )
    org_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # The LiteLLM registration (utils/litellm.py); NULL when the proxy is
    # not configured or the engine has no LiteLLM route.
    litellm_model_name = Column(String, nullable=True)
    litellm_model_id = Column(String, nullable=True)
    # The serving option's reference (Phase 3), when the instance was
    # launched from one: an Ollama tag, a Hugging Face repo, a
    # ``hf.co/<repo>:<quant>`` GGUF pull, or a hosted provider model id.
    # Every consumer reads ``instance.reference or instance.model.modelId``.
    reference = Column(String, nullable=True)
    # Migration 0008. ``status`` is Pending, Running, Failed or Stopped,
    # written by the platform (operations stream); NULL means "derive
    # from the pod". ``last_error`` is the Helm or Kubernetes error
    # text, at most 4000 characters.
    status = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    # Chosen at launch; the server default keeps pre-0008 rows at 1.
    replicas = Column(Integer, nullable=False, default=1, server_default="1")
    gpu_count = Column(Integer, nullable=False, default=1, server_default="1")
    # Kubernetes quantities such as "2" and "8Gi"; NULL means chart default.
    cpu = Column(String, nullable=True)
    memory = Column(String, nullable=True)
    stopped_at = Column(DateTime, nullable=True)

    model = relationship("DBModel")
    engine = relationship("DBEngine")
    config = relationship("DBInferenceInstanceConfigParams")
