"""Where a hosted provider's API key lives.

``KubernetesSecretStore`` writes the same shape ``utils/credentials.py``
uses for workload credentials; ``MemorySecretStore`` is an in-process
stand-in so the Playwright fast tier can exercise the Providers page
without a cluster (``AIOPS_SECRET_STORE=memory``, honoured only with
``TEST_MODE=true``, like ``AUTH_MODE=disabled``).
"""

import os
from typing import Protocol

from utils.credentials import _apply_secret, _delete_secret, _secret_body
from utils.kubernetes_utils import get_core_v1_client

SECRET_STORE_ENV = "AIOPS_SECRET_STORE"


class SecretStore(Protocol):
    def write(
        self, namespace: str, name: str, data: dict[str, str]
    ) -> None: ...

    def read(self, namespace: str, name: str, key: str) -> str | None: ...

    def delete(self, namespace: str, name: str) -> None: ...


class KubernetesSecretStore:
    """Secrets in the cluster, via ``get_core_v1_client()`` by default.

    ``core_v1`` is resolved lazily on first use rather than in
    ``__init__``, so constructing the store never touches the
    kubeconfig on its own.
    """

    def __init__(self, core_v1=None):
        self._core_v1 = core_v1

    def _client(self):
        if self._core_v1 is None:
            self._core_v1 = get_core_v1_client()
        return self._core_v1

    def write(self, namespace: str, name: str, data: dict[str, str]) -> None:
        _apply_secret(
            self._client(), namespace, _secret_body(name, namespace, data)
        )

    def read(self, namespace: str, name: str, key: str) -> str | None:
        from base64 import b64decode

        from kubernetes.client.exceptions import ApiException

        try:
            secret = self._client().read_namespaced_secret(
                name=name, namespace=namespace
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise
        encoded = (secret.data or {}).get(key)
        return b64decode(encoded).decode() if encoded else None

    def delete(self, namespace: str, name: str) -> None:
        _delete_secret(self._client(), namespace, name)


# TEST_MODE only: {(namespace, name): {key: value}}.
_memory: dict[tuple[str, str], dict[str, str]] = {}


class MemorySecretStore:
    """A module-level dict, for the fast tier without a cluster."""

    def write(self, namespace: str, name: str, data: dict[str, str]) -> None:
        _memory.setdefault((namespace, name), {}).update(data)

    def read(self, namespace: str, name: str, key: str) -> str | None:
        return _memory.get((namespace, name), {}).get(key)

    def delete(self, namespace: str, name: str) -> None:
        _memory.pop((namespace, name), None)


def get_secret_store() -> SecretStore:
    """``AIOPS_SECRET_STORE=memory`` (with ``TEST_MODE=true``) gives the
    in-process store; anything else gives the Kubernetes store."""
    if os.environ.get(SECRET_STORE_ENV, "").strip().lower() == "memory":
        if os.environ.get("TEST_MODE", "false").lower() != "true":
            raise RuntimeError(
                f"{SECRET_STORE_ENV}=memory needs TEST_MODE=true"
            )
        return MemorySecretStore()
    return KubernetesSecretStore()
