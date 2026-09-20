"""The official MCP registry (registry.modelcontextprotocol.io) as a
source of MCP servers, the way ``huggingface.py`` is a source of models.

An entry can give two things. A ``remote``: a URL that fills the
"Connect a remote server" dialog, after which the URL rule and the
connection test apply as for a typed one, so an entry is never trusted
because it was imported. And a ``deployable``: a container image that
speaks streamable HTTP, which a platform admin imports into the deploy
catalog as a draft and reviews before anybody can run it.

``parse_server`` is a pure function (tested against a recorded
fixture); the HTTP lives in ``search`` and ``fetch``. The registry is a
host we do not run: every answer is read as a stream under a byte cap
and one deadline. Anybody can publish there, so nothing of an entry is
used that the chart cannot express (no docker options, no volumes).
"""

import json
import os
import re
import time
from dataclasses import dataclass, field, replace
from urllib.parse import quote, urlsplit

import certifi
import httpx

from logger import setup_logger
from registry.entry import SourceError
from utils.mcp_catalog_settings import SettingsError, normal_setting

logger = setup_logger(__name__)

REGISTRY_URL_ENV = "AIOPS_MCP_REGISTRY_URL"
DEFAULT_REGISTRY_URL = "https://registry.modelcontextprotocol.io"
SOURCE = "mcp-registry"
TIMEOUT = httpx.Timeout(10.0)
MAX_BODY = 2 * 1024 * 1024
DEADLINE_SECONDS = 15.0
CACHE_SECONDS = 60.0
MAX_LIMIT = 50
MAX_QUERY = 100

TRANSPORT_HTTP = "streamable-http"
TRANSPORT_SSE = "sse"
# The platform's names for them (``api.mcp.TRANSPORTS``).
_PLATFORM_TRANSPORT = {TRANSPORT_HTTP: "http", TRANSPORT_SSE: "sse"}
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
BIND_ALL = "0.0.0.0"
_SLUG_MAX = 32


@dataclass(frozen=True)
class RemoteForm:
    """What fills the add dialog."""

    url: str
    transport: str  # http | sse
    auth_type: str  # none | bearer | header
    auth_header: str | None = None


@dataclass(frozen=True)
class DeployableForm:
    """What becomes a draft catalog entry."""

    image: str
    tag: str
    args: list[str]
    port: int
    path: str
    settings: list[dict]
    # What the parser changed or could not take over, for the reviewer.
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class McpRegistryEntry:
    name: str
    title: str
    description: str | None
    version: str | None
    publisher: str
    website: str | None
    remote: RemoteForm | None
    remote_reason: str | None
    deployable: DeployableForm | None
    deployable_reason: str | None
    raw: dict


def registry_url() -> str | None:
    """None turns import off. Unset means the public registry; the
    chart always renders the variable, and empty is "off"."""
    value = os.environ.get(REGISTRY_URL_ENV)
    if value is None:
        return DEFAULT_REGISTRY_URL
    return value.strip().rstrip("/") or None


def catalog_slug(name: str) -> str:
    """A catalog name (``utils.mcp.valid_name``) from a registry name:
    the last part, lower case, other characters to ``_``, a leading
    non-letter gets ``s``, at most 32, no ``_`` at the end. It is a
    suggestion: many entries end in ``mcp`` or ``server``, so an import
    can name another."""
    last = name.rsplit("/", 1)[-1].lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", last).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug or not slug[0].isalpha():
        slug = f"s{slug}"
    return slug[:_SLUG_MAX].rstrip("_")


# --- the remote form ---------------------------------------------------


def _remote(server: dict) -> tuple[RemoteForm | None, str | None]:
    remotes = [r for r in server.get("remotes") or [] if isinstance(r, dict)]
    if not remotes:
        return None, None
    chosen = next(
        (r for r in remotes if r.get("type") == TRANSPORT_HTTP), None
    ) or next((r for r in remotes if r.get("type") == TRANSPORT_SSE), None)
    if chosen is None:
        return None, "No streamable HTTP or SSE endpoint"
    url = str(chosen.get("url") or "")
    if _PLACEHOLDER.search(url):
        return None, "The URL needs values of yours; enter it by hand"
    headers = [
        h
        for h in chosen.get("headers") or []
        if isinstance(h, dict) and (h.get("isSecret") or h.get("isRequired"))
    ]
    if len(headers) > 1:
        return None, "Needs more than one credential header"
    transport = _PLATFORM_TRANSPORT[chosen["type"]]
    if not headers:
        return RemoteForm(url, transport, "none"), None
    header = str(headers[0].get("name") or "")
    if header.lower() == "authorization":
        return RemoteForm(url, transport, "bearer"), None
    return RemoteForm(url, transport, "header", header), None


# --- the deployable form -----------------------------------------------


def _split_image(identifier: str) -> tuple[str, str] | None:
    """``(repository, tag)`` of ``host/repo:tag`` or
    ``host/repo@sha256:...``; None without a registry host or a pinned
    version, so what a platform admin read is what runs."""
    if "@" in identifier:
        repository, _, digest = identifier.partition("@")
        tag = f"@{digest}" if digest.startswith("sha256:") else ""
    else:
        repository, _, tag = identifier.rpartition(":")
        if "/" in tag:  # the colon was a port: no tag at all
            repository, tag = identifier, ""
    host = repository.split("/", 1)[0]
    if "/" not in repository or not ("." in host or ":" in host):
        return None
    if not tag or tag == "latest":
        return None
    return repository, tag


def _default(item: dict) -> str | None:
    value = item.get("value", item.get("default"))
    return None if value is None else str(value)


def _is_bind_host(name: str, value: str | None) -> bool:
    lowered = name.lower()
    return value in _LOOPBACK and "host" in lowered and "allow" not in lowered


def _deployable(server: dict) -> tuple[DeployableForm | None, str | None]:
    packages = [p for p in server.get("packages") or [] if isinstance(p, dict)]
    if not packages:
        return None, None
    images = [
        p
        for p in packages
        if p.get("registryType") == "oci"
        and (p.get("transport") or {}).get("type") == TRANSPORT_HTTP
    ]
    if not images:
        return None, "A stdio package; it needs an adapter"
    package = images[0]
    transport = package.get("transport") or {}
    runtime = [
        str(a.get("name") or a.get("value") or "?")
        for a in package.get("runtimeArguments") or []
        if isinstance(a, dict)
    ]
    if runtime:
        return None, f"Needs docker run options ({', '.join(runtime[:4])})"
    if transport.get("headers"):
        return None, "The server checks a header of its own"
    image = _split_image(str(package.get("identifier") or ""))
    if image is None:
        return None, "The image has no registry host or no pinned version"

    arguments = [
        a for a in package.get("packageArguments") or [] if isinstance(a, dict)
    ]
    variables = [
        v
        for v in package.get("environmentVariables") or []
        if isinstance(v, dict) and v.get("name")
    ]
    known = {str(a["name"]): _default(a) for a in arguments if a.get("name")}
    known.update({str(v["name"]): _default(v) for v in variables})

    url = str(transport.get("url") or "")
    names = _PLACEHOLDER.findall(url)
    host_names = set()
    resolved = url
    for name in names:
        value = known.get(name)
        if value is None:
            return None, f"The endpoint needs a value for {name}"
        resolved = resolved.replace(f"{{{name}}}", value)
    parts = urlsplit(resolved)
    split = urlsplit(url)
    if split.hostname and _PLACEHOLDER.fullmatch(
        split.netloc.split(":")[0] or ""
    ):
        host_names.add(split.netloc.split(":")[0].strip("{}"))
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        return None, "The endpoint names no port"
    path = parts.path or "/"
    # The path goes into the proxy registration URL as it is.
    if (
        not path.startswith("/")
        or parts.query
        or parts.fragment
        or re.search(r"[\s?#]", path)
    ):
        return None, "The endpoint's path is not usable"

    notes: list[str] = []
    args: list[str] = []
    for argument in arguments:
        name = str(argument.get("name") or "")
        value = _default(argument)
        if name in host_names or _is_bind_host(name, value):
            notes.append(f"{name} set to {BIND_ALL} (was {value})")
            value = BIND_ALL
        if value is None:
            if argument.get("isRequired"):
                notes.append(f"{name or 'an argument'} needs a value")
            continue
        args.extend(
            [name, value] if argument.get("type") == "named" else [value]
        )

    settings: list[dict] = []
    for variable in variables:
        name = str(variable["name"])
        try:
            normal_setting({"name": name})
        except SettingsError:
            notes.append(f"{name} is no usable setting; left out")
            continue
        secret = bool(variable.get("isSecret"))
        default = None if secret else _default(variable)
        if name in host_names or _is_bind_host(name, default):
            notes.append(f"{name} set to {BIND_ALL} (was {default})")
            default = BIND_ALL
        settings.append(
            {
                "name": name,
                "label": name,
                "help": str(variable.get("description") or "")[:300],
                "secret": secret,
                "required": bool(variable.get("isRequired")),
                "default": default,
            }
        )
    return (
        DeployableForm(image[0], image[1], args, port, path, settings, notes),
        None,
    )


class EntryError(ValueError):
    """An entry whose shape is not the registry's schema. Anybody can
    publish there, so one such entry must never be more than one entry
    that is left out."""


def parse_server(entry: dict) -> McpRegistryEntry:
    try:
        return _parse_server(entry)
    except EntryError:
        raise
    except Exception as e:  # noqa: BLE001 - hostile data, any shape
        raise EntryError(f"not a registry entry: {type(e).__name__}") from e


def _text(value, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _web_url(value) -> str | None:
    """It becomes a link for every member: http(s) only."""
    text = _text(value, 500)
    if text and urlsplit(text).scheme in ("http", "https"):
        return text
    return None


def _parse_server(entry: dict) -> McpRegistryEntry:
    """One element of the registry's ``servers`` list, or the answer of
    its read-one route."""
    server = entry.get("server") if "server" in entry else entry
    if not isinstance(server, dict) or not isinstance(server.get("name"), str):
        raise EntryError("an entry has no name")
    name = server["name"][:200]
    remote, remote_reason = _remote(server)
    deployable, deployable_reason = _deployable(server)
    return McpRegistryEntry(
        name=name,
        title=_text(server.get("title"), 100) or name.rsplit("/", 1)[-1],
        description=_text(server.get("description"), 1000),
        version=_text(server.get("version"), 100),
        publisher=name.rsplit("/", 1)[0] if "/" in name else name,
        website=_web_url(server.get("websiteUrl"))
        or _web_url(
            server["repository"].get("url")
            if isinstance(server.get("repository"), dict)
            else None
        ),
        remote=remote,
        remote_reason=remote_reason,
        deployable=deployable,
        deployable_reason=deployable_reason,
        raw=server,
    )


# --- the client --------------------------------------------------------

_cache: dict[tuple[str, str, int], tuple[float, list[McpRegistryEntry]]] = {}
# A writer chooses the query, so the keys are bounded.
CACHE_MAX_KEYS = 256


def _remember(key, entries: list[McpRegistryEntry]) -> None:
    now = time.monotonic()
    for old in [k for k, (until, _) in _cache.items() if until <= now]:
        del _cache[old]
    while len(_cache) >= CACHE_MAX_KEYS:
        del _cache[next(iter(_cache))]
    _cache[key] = (now + CACHE_SECONDS, entries)


def http_client() -> httpx.Client:
    """A seam for the tests. The certifi bundle: ``SSL_CERT_FILE`` can
    point at a private CA only."""
    return httpx.Client(
        verify=certifi.where(), timeout=TIMEOUT, follow_redirects=False
    )


def _base() -> str:
    base = registry_url()
    if base is None:
        raise SourceError(404, "Import is turned off")
    return base


def _get(path: str, params: dict | None = None) -> dict:
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        with (
            http_client() as client,
            client.stream(
                "GET",
                f"{_base()}{path}",
                params=params,
                headers={"Accept": "application/json"},
            ) as response,
        ):
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                detail = "The MCP registry rate limited the request"
                if retry_after:
                    detail += f"; retry after {retry_after}"
                raise SourceError(429, detail)
            if response.status_code == 404:
                raise SourceError(404, "The MCP registry has no such entry")
            if response.status_code >= 400:
                raise SourceError(
                    502, f"The MCP registry answered {response.status_code}"
                )
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BODY or time.monotonic() > deadline:
                    raise SourceError(
                        502, "The MCP registry's answer is too large or slow"
                    )
                chunks.append(chunk)
    except httpx.HTTPError as e:
        raise SourceError(502, f"Could not reach the MCP registry: {e}") from e
    try:
        body = json.loads(b"".join(chunks))
    except ValueError as e:
        raise SourceError(502, "The MCP registry sent no JSON") from e
    if not isinstance(body, dict):
        raise SourceError(502, "The MCP registry sent no JSON object")
    return body


def search(query: str, limit: int = 20) -> list[McpRegistryEntry]:
    """The latest version of each entry whose name matches. Cached for
    a minute: a dialog searches on every submit, and the registry is a
    shared public service."""
    key = (_base(), query, limit)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    body = _get(
        "/v0/servers",
        {"search": query, "limit": limit, "version": "latest"},
    )
    items = body.get("servers")
    entries = []
    for item in items if isinstance(items, list) else []:
        try:
            # ``raw`` is for an import, which fetches the entry again:
            # a preview does not keep it, and the cache stays small.
            entries.append(replace(parse_server(item), raw={}))
        except EntryError as e:
            logger.info("MCP registry: an entry is left out (%s)", e)
    _remember(key, entries)
    return entries


def fetch(name: str, version: str = "latest") -> McpRegistryEntry:
    """One entry. The ``/`` of the name must be encoded (measured:
    without ``/versions/<v>`` the registry answers 404)."""
    body = _get(
        f"/v0/servers/{quote(name, safe='')}/versions/{quote(version, safe='')}"
    )
    try:
        return parse_server(body)
    except EntryError as e:
        raise SourceError(502, f"The MCP registry sent {e}") from e
