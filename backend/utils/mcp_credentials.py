"""The credentials of MCP servers: where they are stored and how one
becomes request headers.

``resolve`` is the one place that answers "which headers does this
caller's request to this server carry". With no credential, or one the
organization shares (LiteLLM holds a copy of it), the relay adds
nothing. Where each member brings their own (``per_user``), the value
is read from the member's Secret and goes to LiteLLM as
``x-mcp-<alias>-<header>``, which the proxy forwards to that server for
that call only (measured: two callers, two credentials, no mixing).
OAuth is a later mode of the same call. The Secret is the source of
truth in every mode.
"""

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth.current_user import CurrentUser
from models.mcp_server import McpCredential, McpServer
from models.membership import Membership
from utils import mcp_oauth
from utils.gateway import id8
from utils.kubernetes_utils import get_default_namespace
from utils.secret_store import get_secret_store

SECRET_KEY = "credential"
MODE_NONE = "none"
MODE_SHARED = "shared"
MODE_PER_USER = "per_user"
CREDENTIAL_MODES = (MODE_NONE, MODE_SHARED, MODE_PER_USER)
# A member's value is read on every MCP request; keep it this long.
VALUE_CACHE_SECONDS = 60.0
# After a refresh that failed for a passing reason, the old token is
# used this long before the next try.
RETRY_AFTER_SECONDS = 10.0
# Looks at the Secret after ``invalid_grant``, for another replica's write.
RACE_WAITS_SECONDS = (0.0, 0.5, 1.5)
_value_cache: dict[str, tuple[float, str]] = {}
AUTH_BEARER = "bearer"
AUTH_HEADER = "header"
AUTH_TYPES = (AUTH_BEARER, AUTH_HEADER)
# A per_user server whose members sign in (``utils/mcp_oauth.py``): the
# member's Secret then holds the access token under SECRET_KEY, as for
# a pasted token, plus what a refresh needs.
AUTH_OAUTH = "oauth"
REFRESH_KEY = "refresh_token"
EXPIRES_KEY = "expires_at"
CLIENT_SECRET_KEY = "client_secret"

# What GET /mcp/servers says about the caller's own credential.
NOT_NEEDED = "not_needed"
SET = "set"
MISSING = "missing"


@dataclass(frozen=True)
class Resolved:
    """``state`` is one of NOT_NEEDED, SET, MISSING; ``headers`` is
    what the relay must add for this caller (nothing while LiteLLM
    holds the shared credential)."""

    state: str
    headers: dict[str, str]


def shared_secret_name(server_id: uuid.UUID) -> str:
    return f"mcp-{id8(server_id)}-credentials"


def oauth_client_secret_name(server_id: uuid.UUID) -> str:
    return f"mcp-{id8(server_id)}-oauth-client"


def user_secret_name(server_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"mcp-{id8(server_id)}-usr-{id8(user_id)}-credentials"


def credential_headers(
    auth_type: str, auth_header: str | None, value: str
) -> dict[str, str]:
    """The upstream request headers one credential value becomes."""
    if auth_type == AUTH_HEADER:
        return {auth_header or "Authorization": value}
    return {"Authorization": f"Bearer {value}"}


def shared_credential(server: McpServer) -> McpCredential | None:
    return next((c for c in server.credentials if c.user_id is None), None)


def store_shared(
    db: Session,
    server: McpServer,
    auth_type: str,
    auth_header: str | None,
    value: str,
) -> McpCredential:
    """Write the Secret first, then the row that points at it."""
    name = shared_secret_name(server.id)
    get_secret_store().write(
        get_default_namespace(), name, {SECRET_KEY: value}
    )
    row = shared_credential(server)
    if row is None:
        row = McpCredential(server_id=server.id, user_id=None)
        server.credentials.append(row)
    row.secret_name = name
    row.auth_type = auth_type
    row.auth_header = auth_header if auth_type == AUTH_HEADER else None
    # Said explicitly: a new value in the same header shape changes no
    # column, so ``onupdate`` would leave the "set" date of the old one.
    row.updated_at = datetime.now()
    db.flush()
    return row


def read_value(credential: McpCredential) -> str | None:
    return get_secret_store().read(
        get_default_namespace(), credential.secret_name, SECRET_KEY
    )


def delete_all(server: McpServer) -> None:
    """Every Secret of the server; the rows go with the server."""
    store = get_secret_store()
    namespace = get_default_namespace()
    for credential in list(server.credentials):
        store.delete(namespace, credential.secret_name)
        _value_cache.pop(credential.secret_name, None)
    # Not a credential row, so by name (a delete of nothing is fine).
    store.delete(namespace, oauth_client_secret_name(server.id))


def delete_shared(db: Session, server: McpServer) -> None:
    row = shared_credential(server)
    if row is None:
        return
    get_secret_store().delete(get_default_namespace(), row.secret_name)
    server.credentials.remove(row)
    db.flush()


def user_credential(
    server: McpServer, user_id: uuid.UUID
) -> McpCredential | None:
    return next((c for c in server.credentials if c.user_id == user_id), None)


def store_for_user(
    db: Session, server: McpServer, user_id: uuid.UUID, value: str
) -> McpCredential:
    """A member's own value, in the header shape the server asks for."""
    name = user_secret_name(server.id, user_id)
    get_secret_store().write(
        get_default_namespace(), name, {SECRET_KEY: value}
    )
    _value_cache.pop(name, None)
    row = user_credential(server, user_id)
    if row is None:
        row = McpCredential(server_id=server.id, user_id=user_id)
        server.credentials.append(row)
    row.secret_name = name
    row.auth_type = server.user_auth_type or AUTH_BEARER
    row.auth_header = server.user_auth_header
    row.updated_at = datetime.now()
    db.flush()
    return row


def delete_for_user_on_server(
    db: Session, server: McpServer, user_id: uuid.UUID
) -> bool:
    row = user_credential(server, user_id)
    if row is None:
        return False
    get_secret_store().delete(get_default_namespace(), row.secret_name)
    _value_cache.pop(row.secret_name, None)
    server.credentials.remove(row)
    db.flush()
    return True


def delete_for_user(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Every credential a member stored in one organization: what
    ``remove_member`` calls. It raises when a Secret cannot be deleted,
    and the caller then keeps the member: a removed member's token must
    not stay in the cluster. A platform server belongs to no
    organization, so what the member stored for one goes with their
    last membership."""
    elsewhere = (
        db.query(Membership.id)
        .filter(Membership.user_id == user_id, Membership.org_id != org_id)
        .first()
        is not None
    )
    of_this_member = McpServer.org_id == org_id
    if not elsewhere:
        of_this_member = or_(of_this_member, McpServer.org_id.is_(None))
    rows = (
        db.query(McpCredential)
        .join(McpServer, McpCredential.server_id == McpServer.id)
        .filter(of_this_member, McpCredential.user_id == user_id)
        .all()
    )
    store = get_secret_store()
    namespace = get_default_namespace()
    for row in rows:
        store.delete(namespace, row.secret_name)
        _value_cache.pop(row.secret_name, None)
        db.delete(row)
    db.flush()
    return len(rows)


def delete_personal_servers(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID, litellm=None
) -> int:
    """The servers a member added for themselves in one organization,
    with their Secrets: what ``remove_member`` calls, next to
    ``delete_for_user``. The proxy's registration goes best effort (a
    server nobody can select any more is inert there); a Secret that
    cannot be deleted raises, and the member stays."""
    servers = (
        db.query(McpServer)
        .filter(McpServer.org_id == org_id, McpServer.owner_id == user_id)
        .all()
    )
    for server in servers:
        delete_all(server)
        if litellm is not None and server.litellm_server_id:
            try:
                litellm.delete_mcp_server(server.litellm_server_id)
            except Exception:  # noqa: BLE001 - best effort, see above
                pass
        db.delete(server)
    db.flush()
    return len(servers)


def store_oauth_client_secret(server: McpServer, secret: str) -> None:
    get_secret_store().write(
        get_default_namespace(),
        oauth_client_secret_name(server.id),
        {CLIENT_SECRET_KEY: secret},
    )


def read_oauth_client_secret(server: McpServer) -> str | None:
    return get_secret_store().read(
        get_default_namespace(),
        oauth_client_secret_name(server.id),
        CLIENT_SECRET_KEY,
    )


def _token_data(tokens: mcp_oauth.Tokens) -> dict[str, str]:
    data = {SECRET_KEY: tokens.access_token}
    if tokens.refresh_token:
        data[REFRESH_KEY] = tokens.refresh_token
    if tokens.expires_at is not None:
        data[EXPIRES_KEY] = str(tokens.expires_at)
    return data


def store_oauth_tokens(
    db: Session,
    server: McpServer,
    user_id: uuid.UUID,
    tokens: mcp_oauth.Tokens,
) -> McpCredential:
    """What a member's sign-in gave: the Secret, then the row."""
    name = user_secret_name(server.id, user_id)
    store = get_secret_store()
    # A write replaces the whole Secret. No delete first: a reader in
    # between would find nothing and tell the member to sign in.
    store.write(get_default_namespace(), name, _token_data(tokens))
    _value_cache.pop(name, None)
    row = user_credential(server, user_id)
    if row is None:
        row = McpCredential(server_id=server.id, user_id=user_id)
        server.credentials.append(row)
    row.secret_name = name
    row.auth_type = AUTH_BEARER
    row.auth_header = None
    row.updated_at = datetime.now()
    db.flush()
    return row


_refresh_locks: dict[str, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _refresh_lock(name: str) -> threading.Lock:
    with _refresh_locks_guard:
        return _refresh_locks.setdefault(name, threading.Lock())


def _expiry(data: dict[str, str]) -> float | None:
    try:
        return float(data[EXPIRES_KEY])
    except (KeyError, ValueError):
        return None


def _fresh(data: dict[str, str]) -> bool:
    expiry = _expiry(data)
    return (
        expiry is None
        or expiry - time.time() > mcp_oauth.REFRESH_MARGIN_SECONDS
    )


def _cache_token(name: str, data: dict[str, str]) -> str:
    """Never longer than the token lives, less the refresh margin."""
    ttl = VALUE_CACHE_SECONDS
    expiry = _expiry(data)
    if expiry is not None:
        left = expiry - time.time() - mcp_oauth.REFRESH_MARGIN_SECONDS
        ttl = max(0.0, min(ttl, left))
    _value_cache[name] = (time.monotonic() + ttl, data[SECRET_KEY])
    return data[SECRET_KEY]


def oauth_access_token(
    db: Session | None, server: McpServer, row: McpCredential
) -> str | None:
    """A member's access token, refreshed first when it ends within the
    margin. One refresh at a time for each Secret in this process, with
    the Secret read again after the lock. Another replica can still win
    the race: when the authorization server then refuses our refresh
    token (``invalid_grant``), the Secret is read once more, and a token
    the other replica wrote is used. When that does not help either,
    the sign-in is over: the Secret and the row go, so the list says
    ``missing`` and the UI offers the sign-in again. A network failure
    deletes nothing."""
    name = row.secret_name
    hit = _value_cache.get(name)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    store = get_secret_store()
    namespace = get_default_namespace()
    data = store.read_all(namespace, name)
    if not data or SECRET_KEY not in data:
        return None
    if _fresh(data):
        return _cache_token(name, data)
    with _refresh_lock(name):
        data = store.read_all(namespace, name) or {}
        if SECRET_KEY in data and _fresh(data):
            return _cache_token(name, data)
        refresh_token = data.get(REFRESH_KEY)
        try:
            if not refresh_token or not server.oauth:
                raise mcp_oauth.OAuthError(
                    "no refresh token", invalid_grant=True
                )
            tokens = mcp_oauth.refresh(
                server.oauth,
                read_oauth_client_secret(server),
                server.url,
                refresh_token,
            )
        except mcp_oauth.OAuthError as e:
            if not e.invalid_grant:
                # Transient: the old token while it still works at all.
                expiry = _expiry(data)
                if SECRET_KEY in data and (
                    expiry is None or expiry > time.time()
                ):
                    # Kept for a moment, so the next calls do not each
                    # wait for the same failure under the lock.
                    _value_cache[name] = (
                        time.monotonic() + RETRY_AFTER_SECONDS,
                        data[SECRET_KEY],
                    )
                    return data[SECRET_KEY]
                return None
            # Another replica may have used the refresh token first and
            # be about to write the new pair: look a few times before the
            # sign-in is given up.
            for wait in RACE_WAITS_SECONDS:
                time.sleep(wait)
                again = store.read_all(namespace, name) or {}
                if (
                    again.get(REFRESH_KEY) != refresh_token
                    and SECRET_KEY in again
                ):
                    return _cache_token(name, again)
            store.delete(namespace, name)
            _value_cache.pop(name, None)
            if db is not None:
                server.credentials.remove(row)
                db.commit()
            return None
        fresh = _token_data(tokens)
        store.write(namespace, name, fresh)
        return _cache_token(name, fresh)


def _cached_value(credential: McpCredential) -> str | None:
    hit = _value_cache.get(credential.secret_name)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = read_value(credential)
    if value is not None:
        _value_cache[credential.secret_name] = (
            time.monotonic() + VALUE_CACHE_SECONDS,
            value,
        )
    return value


def state(server: McpServer, user: CurrentUser) -> str:
    """NOT_NEEDED, SET or MISSING, from the rows alone (no Secret read):
    what the server list shows."""
    if server.credential_mode != MODE_PER_USER:
        return NOT_NEEDED
    return SET if user_credential(server, user.id) else MISSING


def forwarded_headers(alias: str, headers: dict[str, str]) -> dict[str, str]:
    """The proxy's per-call form of upstream headers for one server."""
    return {f"x-mcp-{alias}-{name.lower()}": v for name, v in headers.items()}


def is_oauth(server: McpServer) -> bool:
    return (
        server.credential_mode == MODE_PER_USER
        and server.user_auth_type == AUTH_OAUTH
    )


def resolve(
    server: McpServer,
    user: CurrentUser,
    alias: str,
    db: Session | None = None,
) -> Resolved:
    """See the module docstring. ``alias`` is the server's name in the
    proxy, which the per-call header form needs; ``db`` lets an OAuth
    sign-in that is over remove its row."""
    if server.credential_mode != MODE_PER_USER:
        return Resolved(NOT_NEEDED, {})
    row = user_credential(server, user.id)
    if row is None:
        value = None
    elif is_oauth(server):
        value = oauth_access_token(db, server, row)
    else:
        value = _cached_value(row)
    if value is None:
        return Resolved(MISSING, {})
    upstream = credential_headers(row.auth_type, row.auth_header, value)
    return Resolved(SET, forwarded_headers(alias, upstream))
