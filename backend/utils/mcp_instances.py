"""What a deployed MCP server needs outside its router and its
controller: its names, who may call its pod, and the one answer to "can
it take a request"."""

import hashlib
import json
import os
import re
import uuid

from models.mcp_instance import McpInstance
from models.mcp_server import McpServer
from utils.gateway import id8

SOURCE_DEPLOYED = "deployed"
STATUS_CONNECTED = "connected"
STATUS_UNREACHABLE = "unreachable"

LITELLM_NAMESPACE_ENV = "AIOPS_LITELLM_NAMESPACE"
LITELLM_POD_LABELS_ENV = "AIOPS_LITELLM_POD_LABELS"
_LABEL_KEY = re.compile(
    r"^([a-z0-9]([-a-z0-9.]*[a-z0-9])?/)?[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$"
)
_LABEL_VALUE = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")
_NAMESPACE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class ProxySelectorError(Exception):
    """The backend does not know which pods are the proxy's, so it
    cannot render the rule that admits only them."""


def release_name(instance_id: uuid.UUID) -> str:
    """Also the Service (``fullnameOverride``) and the Secrets' prefix.
    ``mcpi``, not ``mcp``: ``mcp-<id8>-credentials`` is a registry
    server's shared credential. The LAST eight hex characters, as the
    hostnames use: ``TEST_MODE`` ids share their first ones."""
    return f"mcpi-{id8(instance_id)}"


def env_secret_name(instance_id: uuid.UUID) -> str:
    return f"{release_name(instance_id)}-env"


def service_host(instance_id: uuid.UUID, namespace: str) -> str:
    return f"{release_name(instance_id)}.{namespace}.svc"


def service_url(
    instance_id: uuid.UUID, namespace: str, port: int, path: str
) -> str:
    """Where the proxy reaches the pod. Computed, never from input: it
    is ``http`` and inside the cluster, which the URL rule refuses for
    every URL that somebody typed."""
    return f"http://{service_host(instance_id, namespace)}:{port}{path}"


def settings_checksum(plain: dict[str, str], secret: dict[str, str]) -> str:
    """Changes when any setting does, a secret one included, so the
    Deployment rolls; the secret values themselves stay out of the
    release's values."""
    body = json.dumps([plain, secret], sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()[:32]


def proxy_selector() -> tuple[str, dict[str, str]]:
    """``(namespace, pod labels)`` of the LiteLLM proxy, the only caller
    the chart's network policy admits."""
    namespace = os.environ.get(LITELLM_NAMESPACE_ENV, "").strip()
    raw = os.environ.get(LITELLM_POD_LABELS_ENV, "").strip()
    if not namespace or not raw:
        raise ProxySelectorError(
            "Deploying an MCP server needs to know the proxy's pods "
            f"({LITELLM_NAMESPACE_ENV}, {LITELLM_POD_LABELS_ENV}): without "
            "them every pod of the cluster could call the server"
        )
    if not _NAMESPACE.match(namespace):
        raise ProxySelectorError(f"{LITELLM_NAMESPACE_ENV} is no namespace")
    labels: dict[str, str] = {}
    for pair in raw.split(","):
        key, separator, value = pair.strip().partition("=")
        if (
            not separator
            or not _LABEL_KEY.match(key)
            or not _LABEL_VALUE.match(value)
        ):
            raise ProxySelectorError(
                f"{LITELLM_POD_LABELS_ENV} must be label=value pairs"
            )
        labels[key] = value
    return namespace, labels


def usable(server: McpServer, instance: McpInstance | None) -> bool:
    """A deployed server can take a request: its pod serves (what the
    poller's last tick stored), the proxy knows it, and the last
    connection test worked. ``status`` alone is not enough: a Running
    row stays Running while its pod restarts."""
    if instance is None:
        return True
    return bool(
        instance.ready
        and instance.registered_at is not None
        and server.status == STATUS_CONNECTED
    )
