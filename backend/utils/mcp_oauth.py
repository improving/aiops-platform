"""OAuth sign-in to an MCP server, as the MCP authorization
specification defines it (OAuth 2.1: authorization code with PKCE,
RFC 8414 metadata, RFC 9728 protected-resource metadata, RFC 7591
dynamic client registration, RFC 8707 ``resource``).

The platform is the OAuth client and a member is the user: the member
signs in at the server's own authorization server, and the platform
gets an access token it keeps in the member's Secret
(``utils/mcp_credentials.py``). Pure protocol here: no database, no
Secrets, no FastAPI. Every URL comes from an admin-supplied server or
from that server's metadata, so each one passes ``validate_server_url``
before a request, redirects are never followed, and answers are small
and quick or refused. These requests leave the backend pod, which the
proxy's egress policy does not cover: the URL rule is the control.
"""

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import certifi
import httpx

from utils.mcp import McpUrlError, validate_server_url

UI_URL_ENV = "AIOPS_UI_URL"
CALLBACK_PATH = "/mcp-servers/oauth/callback"
CLIENT_NAME = "AIOps platform"
TIMEOUT = httpx.Timeout(10.0)
MAX_BODY = 256 * 1024
# The whole answer, not each read: a server that sends a byte now and
# then must not hold a worker thread (every sync route shares the pool).
DEADLINE_SECONDS = 15.0
# An access token is never taken to live longer than this.
MAX_EXPIRES_IN = 366 * 24 * 3600
STATE_TTL_SECONDS = 600
# Refresh a token that ends within this many seconds.
REFRESH_MARGIN_SECONDS = 60

TOKEN_AUTH_NONE = "none"
TOKEN_AUTH_POST = "client_secret_post"
TOKEN_AUTH_BASIC = "client_secret_basic"


class OAuthError(Exception):
    """A step of the sign-in failed; ``detail`` is safe to show."""

    def __init__(self, detail: str, *, invalid_grant: bool = False):
        super().__init__(detail)
        self.detail = detail
        # The authorization server refused the grant itself (a used or
        # revoked refresh token): signing in again is the only way on.
        self.invalid_grant = invalid_grant


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str | None
    # Seconds since the epoch; None when the server did not say.
    expires_at: float | None


def ui_url() -> str | None:
    value = os.environ.get(UI_URL_ENV, "").strip().rstrip("/")
    return value or None


def redirect_uri() -> str:
    base = ui_url()
    if base is None:
        raise OAuthError(
            f"OAuth sign-in needs the UI's public URL ({UI_URL_ENV})"
        )
    return f"{base}{CALLBACK_PATH}"


def http_client() -> httpx.Client:
    """A seam for the tests. Public hosts: the certifi bundle, because
    ``SSL_CERT_FILE`` can point at a private CA only."""
    return httpx.Client(
        timeout=TIMEOUT, follow_redirects=False, verify=certifi.where()
    )


def _checked(url: str) -> str:
    try:
        return validate_server_url(url)
    except McpUrlError as e:
        raise OAuthError(f"{url}: {e}") from e


def _fetch(
    client: httpx.Client, method: str, url: str, **kwargs
) -> tuple[int, dict | None]:
    """The status and the JSON object of one request to a host we do
    not trust: at most ``MAX_BODY`` bytes and ``DEADLINE_SECONDS`` for
    the whole answer, read as a stream so neither limit is checked after
    the fact. The body is None when it is no JSON object, too large or
    too slow. Raises ``httpx.HTTPError`` when the host is not reached."""
    headers = {"Accept": "application/json", **kwargs.pop("headers", {})}
    deadline = time.monotonic() + DEADLINE_SECONDS
    with client.stream(
        method, _checked(url), headers=headers, **kwargs
    ) as response:
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BODY or time.monotonic() > deadline:
                return response.status_code, None
            chunks.append(chunk)
        status = response.status_code
    try:
        body = json.loads(b"".join(chunks))
    except ValueError:
        return status, None
    return status, body if isinstance(body, dict) else None


def _get_json(client: httpx.Client, url: str) -> dict | None:
    """The JSON object at ``url``, or None when it is not there."""
    try:
        status, body = _fetch(client, "GET", url)
    except httpx.HTTPError as e:
        raise OAuthError(f"Could not reach {url}: {e}") from e
    return body if status == 200 else None


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _well_known(base: str, name: str) -> list[str]:
    """``/.well-known/<name>`` for an issuer or resource with a path:
    the RFC 8414 form first (the path after the well-known part), then
    the plain origin."""
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    urls = [f"{origin}/.well-known/{name}{path}"] if path else []
    urls.append(f"{origin}/.well-known/{name}")
    return urls


def discover(
    server_url: str,
    client: httpx.Client | None = None,
    allow_hosts: list[str] | None = None,
) -> dict:
    """What a sign-in needs to know about ``server_url``: ``issuer``,
    ``authorization_endpoint``, ``token_endpoint``, the optional
    ``registration_endpoint`` and ``scopes_supported``."""
    own = client is None
    client = client or http_client()
    try:
        issuer = _origin(server_url)
        for url in _well_known(server_url, "oauth-protected-resource"):
            resource = _get_json(client, url)
            servers = (resource or {}).get("authorization_servers")
            if isinstance(servers, list) and servers:
                issuer = str(servers[0])
                break
        metadata = None
        for name in ("oauth-authorization-server", "openid-configuration"):
            for url in _well_known(issuer, name):
                metadata = _get_json(client, url)
                if metadata is not None:
                    break
            if metadata is not None:
                break
    finally:
        if own:
            client.close()
    if metadata is None:
        raise OAuthError(
            "This server publishes no OAuth metadata, so nobody can sign "
            "in to it; use a token if it takes one"
        )
    # RFC 8414: the issuer in the document is the one that was asked.
    if str(metadata.get("issuer", "")).rstrip("/") != issuer.rstrip("/"):
        raise OAuthError("The OAuth metadata names another issuer")
    for key in ("authorization_endpoint", "token_endpoint"):
        if not isinstance(metadata.get(key), str):
            raise OAuthError(f"The OAuth metadata has no {key}")
        _checked(metadata[key])
        # Against a mix-up: metadata that shows the member the consent
        # page of an honest authorization server and sends the code, with
        # its verifier, to a token endpoint of somebody else. Both
        # endpoints belong to the issuer, or to hosts the admin named.
        host = urlsplit(metadata[key]).hostname or ""
        if _origin(metadata[key]) != _origin(issuer) and host not in (
            allow_hosts or ()
        ):
            raise OAuthError(
                f"The {key} is on {host}, not on the issuer "
                f"({urlsplit(issuer).hostname}). If that is right for this "
                "server, name the host in oauth.allow_hosts"
            )
    if "S256" not in (
        metadata.get("code_challenge_methods_supported") or ["S256"]
    ):
        raise OAuthError(
            "The authorization server does not support PKCE (S256)"
        )
    return {
        "issuer": issuer,
        "authorization_endpoint": metadata["authorization_endpoint"],
        "token_endpoint": metadata["token_endpoint"],
        "registration_endpoint": metadata.get("registration_endpoint"),
        "scopes_supported": metadata.get("scopes_supported") or [],
        # RFC 9207: the authorization response then names its issuer.
        "iss_required": metadata.get(
            "authorization_response_iss_parameter_supported"
        )
        is True,
    }


PROBE_DEADLINE_SECONDS = 5.0


def probe(server_url: str, client: httpx.Client | None = None) -> bool:
    """Does this server offer an OAuth sign-in? For the hint of the add
    dialog after a connection test that was refused. It reads the same
    documents as ``discover``, but under ONE deadline for the whole
    probe (``discover`` can make six requests of fifteen seconds each,
    on a thread of the pool that runs every sync route), and it never
    raises: no answer in time is "no"."""
    deadline = time.monotonic() + PROBE_DEADLINE_SECONDS
    own = client is None
    try:
        client = client or httpx.Client(
            timeout=httpx.Timeout(PROBE_DEADLINE_SECONDS / 2),
            follow_redirects=False,
            verify=certifi.where(),
        )
        issuer = _origin(server_url)
        for url in _well_known(server_url, "oauth-protected-resource"):
            if time.monotonic() > deadline:
                return False
            servers = (_get_json(client, url) or {}).get(
                "authorization_servers"
            )
            if isinstance(servers, list) and servers:
                issuer = str(servers[0])
                break
        for name in ("oauth-authorization-server", "openid-configuration"):
            for url in _well_known(issuer, name):
                if time.monotonic() > deadline:
                    return False
                metadata = _get_json(client, url)
                if metadata and isinstance(
                    metadata.get("authorization_endpoint"), str
                ):
                    return True
        return False
    except (OAuthError, httpx.HTTPError, ValueError, TypeError):
        # Never an error: a hostile metadata document is a "no" too.
        return False
    finally:
        if own and client is not None:
            client.close()


def register_client(
    metadata: dict, client: httpx.Client | None = None
) -> tuple[str, str | None]:
    """Dynamic client registration; ``(client_id, client_secret)``."""
    endpoint = metadata.get("registration_endpoint")
    if not endpoint:
        raise OAuthError(
            "The authorization server registers no clients by itself: "
            "create an OAuth application there with the redirect URI "
            f"{redirect_uri()} and give its client id"
        )
    own = client is None
    client = client or http_client()
    try:
        status, body = _fetch(
            client,
            "POST",
            endpoint,
            json={
                "client_name": CLIENT_NAME,
                "redirect_uris": [redirect_uri()],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": TOKEN_AUTH_NONE,
            },
        )
    except httpx.HTTPError as e:
        raise OAuthError(f"Client registration failed: {e}") from e
    finally:
        if own:
            client.close()
    if status not in (200, 201):
        raise OAuthError(f"Client registration answered {status}")
    if body is None or not isinstance(body.get("client_id"), str):
        raise OAuthError("Client registration gave no client id")
    return body["client_id"], body.get("client_secret") or None


def check_issuer(oauth: dict, iss: str | None) -> None:
    """RFC 9207: an authorization response that names another issuer
    than the one the sign-in went to is refused, and one that names none
    where the server promised to."""
    expected = str(oauth.get("issuer", "")).rstrip("/")
    if iss is None:
        if oauth.get("iss_required"):
            raise OAuthError("The answer does not say which server sent it")
        return
    if iss.rstrip("/") != expected:
        raise OAuthError("The answer comes from another authorization server")


def new_state() -> tuple[str, str]:
    """``(state, its hash)``: the hash is what the database keeps."""
    state = secrets.token_urlsafe(32)
    return state, hash_state(state)


def hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def new_verifier() -> str:
    return secrets.token_urlsafe(64)


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorization_url(
    oauth: dict, server_url: str, state: str, verifier: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": oauth["client_id"],
        "redirect_uri": redirect_uri(),
        "state": state,
        "code_challenge": challenge(verifier),
        "code_challenge_method": "S256",
        "resource": server_url,
    }
    if oauth.get("scopes"):
        params["scope"] = " ".join(oauth["scopes"])
    endpoint = oauth["authorization_endpoint"]
    joiner = "&" if "?" in endpoint else "?"
    return f"{endpoint}{joiner}{urlencode(params)}"


def _token_request(
    oauth: dict,
    client_secret: str | None,
    form: dict[str, str],
    client: httpx.Client | None,
) -> Tokens:
    data = {**form, "client_id": oauth["client_id"]}
    auth = None
    method = oauth.get("token_auth") or (
        TOKEN_AUTH_POST if client_secret else TOKEN_AUTH_NONE
    )
    if client_secret and method == TOKEN_AUTH_BASIC:
        auth = (oauth["client_id"], client_secret)
    elif client_secret:
        data["client_secret"] = client_secret
    own = client is None
    client = client or http_client()
    try:
        # Validated again at every use: the endpoint is stored.
        status, body = _fetch(
            client,
            "POST",
            oauth["token_endpoint"],
            data=data,
            auth=auth,
        )
    except httpx.HTTPError as e:
        raise OAuthError(
            f"The token endpoint could not be reached: {e}"
        ) from e
    finally:
        if own:
            client.close()
    body = body or {}
    if status != 200 or "access_token" not in body:
        error = str(body.get("error") or status)
        raise OAuthError(
            f"The authorization server refused: {error}",
            invalid_grant=error == "invalid_grant",
        )
    return Tokens(
        access_token=str(body["access_token"]),
        refresh_token=body.get("refresh_token") or None,
        expires_at=_expires_at(body.get("expires_in")),
    )


def _expires_at(expires_in) -> float | None:
    """``expires_in`` is whatever the server sent: clamped as a number
    before any arithmetic (a huge integer overflows a float)."""
    if isinstance(expires_in, bool) or not isinstance(
        expires_in, (int, float)
    ):
        return None
    if expires_in != expires_in:  # NaN
        return None
    return time.time() + float(min(max(expires_in, 0), MAX_EXPIRES_IN))


def exchange_code(
    oauth: dict,
    client_secret: str | None,
    server_url: str,
    code: str,
    verifier: str,
    client: httpx.Client | None = None,
) -> Tokens:
    return _token_request(
        oauth,
        client_secret,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
            "code_verifier": verifier,
            "resource": server_url,
        },
        client,
    )


def refresh(
    oauth: dict,
    client_secret: str | None,
    server_url: str,
    refresh_token: str,
    client: httpx.Client | None = None,
) -> Tokens:
    tokens = _token_request(
        oauth,
        client_secret,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "resource": server_url,
        },
        client,
    )
    # A server that does not rotate keeps the old refresh token valid.
    if tokens.refresh_token is None:
        return Tokens(tokens.access_token, refresh_token, tokens.expires_at)
    return tokens
