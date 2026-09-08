"""Parse the gateway hostnames of deployed instances.

The builders live in ``utils/gateway.py`` (``instance_hostname``); this is
the inverse, used by the ext-authz endpoint to find the instance behind a
``Host`` header.
"""

import re

from utils.gateway import gateway_settings

# nb-<id8>, vdb-<id8>, vdb-<id8>-api, inf-<id8>; <id8> is
# instance.id.hex[-8:] (see utils/gateway.py id8).
_LABEL = re.compile(
    r"^(?P<kind>nb|vdb|inf)-(?P<id8>[0-9a-f]{8})(?P<suffix>-api)?$"
)
_KINDS_WITH_API_SUFFIX = ("vdb",)
# Langflow's host has no id: one Langflow, its own SecurityPolicy
# (infra/local/langflow/langflow.yaml), the same ext-authz check.
LANGFLOW_KIND = "langflow"


def parse_hostname(host: str) -> tuple[str, str, str] | None:
    """Split an instance host into ``(kind, id8, suffix)``.

    The host is lower-cased and a ``:port`` is dropped. With gateway
    settings present the part after the first label must be empty or the
    configured parent domain (another domain is not ours: ``None``).
    Without settings only the first label is parsed. Anything that is not
    an instance host or Langflow (``auth``, a bad id) is ``None``.
    """
    host = host.strip().lower().rsplit(":", 1)[0]
    label, _, rest = host.partition(".")
    settings = gateway_settings()
    if settings is not None and rest and rest != settings.parent_domain:
        return None
    if label == LANGFLOW_KIND:
        return LANGFLOW_KIND, "", ""
    match = _LABEL.match(label)
    if match is None:
        return None
    kind, id8, suffix = match.group("kind", "id8", "suffix")
    suffix = suffix or ""
    if suffix and kind not in _KINDS_WITH_API_SUFFIX:
        return None
    return kind, id8, suffix
