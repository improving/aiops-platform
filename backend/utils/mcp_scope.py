"""Who can see, use and change an MCP server.

Three scopes, from two columns: an organization's server (every member
uses it, an admin changes it), a personal one (``owner_id``: the owner
alone, in the organization it was made in), and a platform one
(``org_id`` NULL: every organization uses it, a platform admin changes
it). ``visible`` is the one filter for lists, the endpoint's selection,
the LiteLLM team and the usage labels, so the four never disagree.
"""

from sqlalchemy import and_, or_

from auth.current_user import CurrentUser
from auth.roles import ROLE_ADMIN, WRITER_ROLES
from models.mcp_server import McpServer

SCOPE_ORGANIZATION = "organization"
SCOPE_PERSONAL = "personal"
SCOPE_PLATFORM = "platform"
SCOPES = (SCOPE_ORGANIZATION, SCOPE_PERSONAL, SCOPE_PLATFORM)


def scope_of(server: McpServer) -> str:
    if server.org_id is None:
        return SCOPE_PLATFORM
    return (
        SCOPE_PERSONAL if server.owner_id is not None else SCOPE_ORGANIZATION
    )


def visible(user: CurrentUser):
    """A SQLAlchemy filter: the servers ``user`` can see and use."""
    return or_(
        McpServer.org_id.is_(None),
        and_(
            McpServer.org_id == user.org_id,
            or_(McpServer.owner_id.is_(None), McpServer.owner_id == user.id),
        ),
    )


def by_name(servers: list[McpServer]) -> dict[str, McpServer]:
    """The server a name means among what one caller sees. A shared
    server and a member's own can carry one name (neither blocks the
    other); the nearer one wins: the member's own, then the
    organization's, then the platform's."""
    nearness = {SCOPE_PLATFORM: 0, SCOPE_ORGANIZATION: 1, SCOPE_PERSONAL: 2}
    chosen: dict[str, McpServer] = {}
    for server in sorted(servers, key=lambda s: nearness[scope_of(s)]):
        chosen[server.name] = server
    return chosen


def can_see(user: CurrentUser, server: McpServer) -> bool:
    if server.org_id is None:
        return True
    if server.org_id != user.org_id:
        return False
    return server.owner_id is None or server.owner_id == user.id


def can_create(user: CurrentUser, scope: str) -> bool:
    if scope == SCOPE_PLATFORM:
        return user.is_platform_admin
    if scope == SCOPE_PERSONAL:
        return user.role in WRITER_ROLES
    return user.role == ROLE_ADMIN


def can_change(user: CurrentUser, server: McpServer) -> bool:
    scope = scope_of(server)
    if scope == SCOPE_PLATFORM:
        return user.is_platform_admin
    if server.org_id != user.org_id:
        return False
    if scope == SCOPE_PERSONAL:
        return server.owner_id == user.id
    return user.role == ROLE_ADMIN
