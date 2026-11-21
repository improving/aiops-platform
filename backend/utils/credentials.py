"""Per-instance workload credentials.

The API key of a deployed instance lives in two Kubernetes Secrets in the
instance's namespace:

- ``<kind>-<id8>-credentials`` with data ``{"api-key": value}``, which
  the workload chart mounts (Tasks 13 and 14);
- ``<kind>-<id8>-apikey-auth`` with data ``{"<resource_id>": value}``,
  the shape Envoy Gateway's ``apiKeyAuth`` SecurityPolicy reads.

The database keeps only the bookkeeping row
(``models/workload_credential.py``): the Secret names and when the value
was shown. Every Kubernetes call goes through ``get_core_v1_client``
from this module, so tests patch ``utils.credentials.get_core_v1_client``.
"""

import base64
import hashlib
import os
import secrets
from uuid import UUID

from kubernetes import client
from kubernetes.client.exceptions import ApiException
from sqlalchemy.orm import Session

from logger import setup_logger
from models.workload_credential import WorkloadCredential
from utils.gateway import MANAGED_BY_LABEL, id8
from utils.kubernetes_utils import get_core_v1_client

logger = setup_logger(__name__)

# The key in the credentials Secret and in the API response.
CREDENTIAL_KEY = "api-key"


def is_test_mode() -> bool:
    return os.environ.get("TEST_MODE", "false").lower() == "true"


def generate_secret(nbytes: int = 32, *, seed: str | None = None) -> str:
    """A URL-safe secret of ``nbytes`` random bytes.

    Under ``TEST_MODE=true`` and with a ``seed`` (the callers pass
    ``str(resource_id)``) the value is a pure function of the seed, so
    the rendered Helm values in ``snapshots/`` stay stable. Without a
    seed the value is random even in test mode.
    """
    if seed is not None and is_test_mode():
        raw = hashlib.shake_256(f"aiops-credential:{seed}".encode()).digest(
            nbytes
        )
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return secrets.token_urlsafe(nbytes)


def credential_secret_names(kind: str, resource_id: UUID) -> tuple[str, str]:
    """``(<kind>-<id8>-credentials, <kind>-<id8>-apikey-auth)``."""
    prefix = f"{kind}-{id8(resource_id)}"
    return f"{prefix}-credentials", f"{prefix}-apikey-auth"


def _secret_body(
    name: str, namespace: str, data: dict[str, str]
) -> client.V1Secret:
    return client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=name, namespace=namespace, labels=dict(MANAGED_BY_LABEL)
        ),
        type="Opaque",
        string_data=data,
    )


def _apply_secret(
    core_v1: client.CoreV1Api, namespace: str, body: client.V1Secret
) -> None:
    """Create the Secret, or replace it when it already exists."""
    name = body.metadata.name
    try:
        core_v1.create_namespaced_secret(namespace=namespace, body=body)
    except ApiException as e:
        if e.status != 409:
            raise
        core_v1.replace_namespaced_secret(
            name=name, namespace=namespace, body=body
        )
        logger.info("Replaced Secret %s/%s", namespace, name)
        return
    logger.info("Created Secret %s/%s", namespace, name)


def _delete_secret(
    core_v1: client.CoreV1Api, namespace: str, name: str
) -> None:
    try:
        core_v1.delete_namespaced_secret(name=name, namespace=namespace)
    except ApiException as e:
        if e.status != 404:
            raise
        logger.info("Secret in %s is already gone", namespace)
        return
    logger.info("Deleted Secret from %s", namespace)


def find_credential(
    db: Session, kind: str, resource_id: UUID
) -> WorkloadCredential | None:
    return (
        db.query(WorkloadCredential)
        .filter(
            WorkloadCredential.resource_kind == kind,
            WorkloadCredential.resource_id == resource_id,
        )
        .first()
    )


def store_credential(
    db: Session, namespace: str, kind: str, resource_id: UUID, value: str
) -> WorkloadCredential:
    """Write both Secrets and upsert the bookkeeping row.

    The Secrets are written first, so a cluster error leaves no row
    behind. Storing again replaces the Secrets and keeps the row (and
    its ``shown_at``).
    """
    secret_name, apikey_secret_name = credential_secret_names(
        kind, resource_id
    )
    core_v1 = get_core_v1_client()
    _apply_secret(
        core_v1,
        namespace,
        _secret_body(secret_name, namespace, {CREDENTIAL_KEY: value}),
    )
    _apply_secret(
        core_v1,
        namespace,
        _secret_body(apikey_secret_name, namespace, {str(resource_id): value}),
    )

    credential = find_credential(db, kind, resource_id)
    if credential is None:
        credential = WorkloadCredential(
            resource_kind=kind, resource_id=resource_id
        )
        db.add(credential)
    credential.namespace = namespace
    credential.secret_name = secret_name
    credential.apikey_secret_name = apikey_secret_name
    db.commit()
    db.refresh(credential)
    return credential


def delete_credential(
    db: Session, namespace: str, kind: str, resource_id: UUID
) -> None:
    """Delete both Secrets (a missing one is fine) and the row."""
    core_v1 = get_core_v1_client()
    for name in credential_secret_names(kind, resource_id):
        _delete_secret(core_v1, namespace, name)
    credential = find_credential(db, kind, resource_id)
    if credential is not None:
        db.delete(credential)
        db.commit()


def read_credential_value(credential: WorkloadCredential) -> str | None:
    """The value in the credentials Secret; None when it is gone.

    Other API errors propagate as ``ApiException``.
    """
    core_v1 = get_core_v1_client()
    try:
        secret = core_v1.read_namespaced_secret(
            name=credential.secret_name, namespace=credential.namespace
        )
    except ApiException as e:
        if e.status == 404:
            return None
        raise
    encoded = (secret.data or {}).get(CREDENTIAL_KEY)
    if encoded is None:
        return None
    return base64.b64decode(encoded).decode("utf-8")
