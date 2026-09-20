"""MCP servers: the name the platform gives one in LiteLLM, the rule an
admin-supplied URL must pass, and the shape of a discovered tool.

The LiteLLM alias is what the model sees: the proxy names every tool
``<alias>-<tool>``. It is ``<name without _><server id8>``, letters and
digits only, for three reasons: it must be unique across organizations
(the id), the first ``-`` of a tool name must end it (no ``-``), and it
is part of an HTTP header name, ``x-mcp-<alias>-authorization``, when a
member's own credential travels with a call: Envoy refuses a header
name with ``_`` (found on the live stack).
"""

import ipaddress
import os
import re
import socket
import uuid
from urllib.parse import urlsplit

from utils.gateway import id8

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,30}[a-z0-9]$|^[a-z]$")
TRANSPORTS = ("http", "sse")
ALLOW_INSECURE_HOSTS_ENV = "AIOPS_MCP_ALLOW_INSECURE_HOSTS"
TOOL_SEPARATOR = "-"

# Never a registered server's address: the cluster's own names.
_INTERNAL_SUFFIXES = (".svc", ".cluster.local", ".internal", ".localhost")


class McpUrlError(ValueError):
    """The URL is not one the platform will connect to."""


def litellm_alias(server_id: uuid.UUID, name: str) -> str:
    return f"{name.replace('_', '')}{id8(server_id)}"


def valid_name(name: str) -> bool:
    return bool(NAME_PATTERN.match(name))


def _allowed_insecure_hosts() -> set[str]:
    raw = os.environ.get(ALLOW_INSECURE_HOSTS_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


def _resolve(host: str) -> list[str]:
    """Every address the host resolves to. A seam for the tests."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def validate_server_url(url: str, *, resolve: bool = True) -> str:
    """The URL, or ``McpUrlError``. An admin's URL is fetched by LiteLLM
    from inside the cluster, so it must be ``https`` and must not name
    or resolve to a loopback, private, link-local or metadata address,
    or a cluster-internal name. A host listed in
    ``AIOPS_MCP_ALLOW_INSECURE_HOSTS`` (local development: the test
    server in kind, which the laptop cannot even resolve) skips both
    rules. ``resolve=False`` (the mock of the fast tier, which has no
    network) keeps every rule but the DNS lookup."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise McpUrlError("The server URL must be an https URL")
    if parts.username or parts.password:
        raise McpUrlError("Put the credential in its field, not in the URL")
    if host in _allowed_insecure_hosts():
        return url.strip()
    if parts.scheme != "https":
        raise McpUrlError("The server URL must use https")
    if host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
        raise McpUrlError("The server URL must be a public address")
    if not resolve and not _is_ip(host):
        return url.strip()
    try:
        addresses = [host] if _is_ip(host) else _resolve(host)
    except OSError:
        raise McpUrlError(f"Could not resolve {host}") from None
    if not addresses or not all(_is_public(a) for a in addresses):
        raise McpUrlError("The server URL must be a public address")
    return url.strip()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def tool_summary(tool: dict) -> dict:
    """What the registry keeps of one discovered tool. ``read_only`` is
    the MCP ``readOnlyHint`` annotation: None when the server sends no
    annotations, so the UI says "changes data" only where it knows."""
    annotations = tool.get("annotations") or {}
    hint = annotations.get("readOnlyHint")
    return {
        "name": tool.get("name", ""),
        "description": tool.get("description") or "",
        "read_only": hint if isinstance(hint, bool) else None,
    }
