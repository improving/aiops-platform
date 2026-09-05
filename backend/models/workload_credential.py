from datetime import datetime

from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from db.database import Base
from utils import genid

# The resource kinds that get a credential (utils/credentials.py).
KIND_VECTORDB = "vdb"
KIND_INFERENCE = "inf"


class WorkloadCredential(Base):
    """The bookkeeping row for one workload's API key.

    The key itself lives in two Kubernetes Secrets (one for the workload
    chart, one for the gateway apiKeyAuth); the row records their names
    and when the value was shown to the owner.
    """

    __tablename__ = "workload_credentials"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=genid.uuid4_gen()
    )
    # vdb or inf.
    resource_kind = Column(String, nullable=False)
    resource_id = Column(UUID(as_uuid=True), nullable=False)
    namespace = Column(String, nullable=False)
    # "<kind>-<id8>-credentials", data {"api-key": value}.
    secret_name = Column(String, nullable=False)
    # "<kind>-<id8>-apikey-auth", data {"<resource_id>": value}.
    apikey_secret_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    # When the value was returned to the owner; None until then.
    shown_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "resource_kind",
            "resource_id",
            name="uq_workload_credentials_resource",
        ),
    )
