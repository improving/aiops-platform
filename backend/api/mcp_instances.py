"""MCP servers the platform deploys (ADR 0011): an organization admin
picks an entry of the deploy catalog, fills its settings, and the
platform runs it with Helm and makes it a server of the MCP registry.

A deployed server is two rows: ``mcp_servers`` (``source =
"deployed"``), so that Chat, the endpoint, Langflow, usage, approval and
the tool allow-list work with no change, and ``mcp_instances``, which
carries what a workload has. Only the LiteLLM proxy talks to the pod:
there is no gateway host, and the chart's network policy admits nobody
else.

The proxy registration is the poller's work (``update_all_mcp_
instances``): at create the pod does not exist, so a connection test
would fail. The poller reads the pods of every instance on every tick
and stores ``ready``, because nothing else reads a Running row again.
"""

import asyncio
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from api import mcp as registry
from api.chat import chat_mock_enabled
from api.instance_inspection import InstanceKind, add_inspection_routes
from auth.current_user import CurrentUser, get_current_user
from controller.mcp_server_controller import DeploySpec, McpServerController
from db.database import get_db
from logger import setup_logger
from models.mcp_catalog import STATUS_PUBLISHED, McpCatalogEntry
from models.mcp_instance import McpInstance
from models.mcp_server import McpServer
from schemas.mcp import McpServerSchema
from schemas.mcp_deploy import (
    McpDeployRequest,
    McpDeploySchema,
    McpInstanceSchema,
    McpInstanceSettingsRequest,
)
from utils import genid, mcp_instances
from utils import mcp_registration as registration
from utils import mcp_scope as scopes
from utils.instance_status import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_STOPPED,
    apply_pod_status,
    mark_failed,
    mark_pending,
)
from utils.kubernetes_utils import (
    get_default_namespace,
    get_pod_status_and_readiness,
)
from utils.litellm import LiteLLMError
from utils.mcp import litellm_alias, tool_summary, valid_name
from utils.mcp_catalog_settings import SettingsError, split_settings
from utils.mcp_instances import (
    SOURCE_DEPLOYED,
    STATUS_CONNECTED,
    STATUS_UNREACHABLE,
    ProxySelectorError,
)
from utils.mcp_mock import MOCK_LITELLM_SERVER_ID, MOCK_TOOLS
from utils.secret_store import get_secret_store

logger = setup_logger(__name__)
router = APIRouter()

INSTANCES = "/v1alpha1/mcp/instances"
APPROVALS = ("never", "writes", "always")
# A pod that is ready this long with no successful registration: the
# proxy cannot reach it, and a person must look.
UNREACHABLE_AFTER = timedelta(minutes=10)
# Mock mode: how long a deployed server reads "Starting".
MOCK_START_SECONDS = 3
MOCK_FAILING_PREFIX = "failing"


class McpInstanceStateSchema(BaseModel):
    """What a restart answers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str | None = None
    ready: bool = False


# --- building blocks ---------------------------------------------------


def startup_of(entry: McpCatalogEntry) -> dict:
    """What an instance copies from its catalog entry, at deploy and at
    an explicit image upgrade."""
    return {
        "command": list(entry.command or []),
        "args": list(entry.args or []),
        "port": entry.port,
        "path": entry.path,
        "egress": entry.egress,
        "schema": list(entry.settings or []),
    }


def _spec(instance: McpInstance, entry: McpCatalogEntry) -> DeploySpec:
    """The release of ``instance`` as it was deployed. Only the chart's
    address is the entry's; the rest is the instance's own copy."""
    startup = instance.startup
    secret = get_secret_store().read_all(
        get_default_namespace(), mcp_instances.env_secret_name(instance.id)
    )
    return DeploySpec(
        instance_id=instance.id,
        image=instance.image,
        tag=instance.tag,
        port=startup["port"],
        path=startup["path"],
        egress=startup["egress"],
        chart_repo=entry.chart_repo,
        chart_name=entry.chart_name,
        command=list(startup["command"]),
        args=list(startup["args"]),
        schema=list(startup["schema"]),
        plain=dict(instance.settings or {}),
        env_secret=mcp_instances.env_secret_name(instance.id)
        if instance.secret_settings
        else "",
        checksum=mcp_instances.settings_checksum(
            instance.settings or {}, secret or {}
        ),
    )


def deploy_block(
    server: McpServer, instance: McpInstance | None
) -> McpDeploySchema | None:
    """The workload side of a server in the list; None for a remote one."""
    if instance is None:
        return None
    entry = instance.catalog
    return McpDeploySchema(
        instance_id=instance.id,
        catalog=entry.name,
        catalog_title=entry.title,
        image=instance.image,
        tag=instance.tag,
        status=instance.status,
        ready=instance.ready,
        launch=instance.launch
        if instance.status not in (STATUS_FAILED, STATUS_STOPPED)
        and not instance.ready
        else None,
        last_error=instance.last_error,
        last_error_at=instance.last_error_at,
        usable=mcp_instances.usable(server, instance),
        upgrade_available=entry.status == STATUS_PUBLISHED
        and (instance.image, instance.tag, instance.startup)
        != (entry.image, entry.tag, startup_of(entry)),
    )


def _instance_response(instance: McpInstance) -> McpInstanceSchema:
    block = deploy_block(instance.server, instance)
    return McpInstanceSchema(
        **block.model_dump(),
        server_id=instance.server_id,
        name=instance.server.name,
        settings=dict(instance.settings or {}),
        secret_settings=list(instance.secret_settings or []),
        schema=list(instance.startup.get("schema") or []),
    )


def _find_instance(
    db: Session, id: uuid.UUID, user: CurrentUser
) -> McpInstance:
    instance = (
        db.query(McpInstance)
        .options(
            joinedload(McpInstance.server), joinedload(McpInstance.catalog)
        )
        .filter(McpInstance.id == id)
        .first()
    )
    # Who sees the registry's row sees its workload: the organization's
    # members, or everybody for a platform server.
    if instance is None or not scopes.can_see(user, instance.server):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return instance


def _find_instance_to_change(
    db: Session, id: uuid.UUID, user: CurrentUser
) -> McpInstance:
    instance = _find_instance(db, id, user)
    _may_change(user, instance, "MCP server")
    return instance


def _may_change(user: CurrentUser, instance: McpInstance, label: str) -> None:
    """An organization admin for the organization's server, a platform
    admin for the platform's (``scopes.can_change``). Not the instance
    policy of the other kinds: that one reads a row without an
    organization as the default organization's."""
    if not scopes.can_change(user, instance.server):
        platform = instance.server.org_id is None
        raise HTTPException(
            status_code=403,
            detail=f"Only {'a platform' if platform else 'an organization'} "
            f"admin can change this {label}",
        )


def _controller() -> McpServerController:
    try:
        return McpServerController()
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Kubernetes is not reachable: {e}"
        ) from e


def _split(entry, given, kept=frozenset()):
    try:
        return split_settings(entry.settings or [], given, kept_secrets=kept)
    except SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _write_secret(instance: McpInstance, secret: dict[str, str]) -> None:
    store = get_secret_store()
    name = mcp_instances.env_secret_name(instance.id)
    if secret:
        store.write(get_default_namespace(), name, secret)
    else:
        store.delete(get_default_namespace(), name)


# --- mock mode ---------------------------------------------------------


def mock_advance(db: Session, instance: McpInstance) -> None:
    """The fast tier has no cluster and no poller. A deployed server is
    Starting until it is a few seconds old, and the next read after that
    finishes it. A function of the instance alone: the specs run in
    parallel on one backend, so a counter of reads would be shared."""
    if instance.registered_at is not None or instance.status == STATUS_FAILED:
        return
    age = datetime.now() - instance.created_at
    if age < timedelta(seconds=MOCK_START_SECONDS):
        return
    server = instance.server
    if server.name.startswith(MOCK_FAILING_PREFIX):
        instance.launch = None
        mark_failed(
            db, instance, "ImagePullBackOff: the image could not be pulled"
        )
        return
    instance.status = STATUS_RUNNING
    instance.ready = True
    instance.launch = None
    instance.registered_at = datetime.now()
    server.litellm_server_id = MOCK_LITELLM_SERVER_ID
    server.tools_cache = [tool_summary(t) for t in MOCK_TOOLS]
    server.status = STATUS_CONNECTED
    server.checked_at = datetime.now()
    db.commit()


_MOCK_LAUNCH = {
    "phase": "Starting",
    "message": "The server is starting",
    "since": None,
    "needs_attention": False,
    "restart_count": 0,
    "replicas_total": 1,
}


def _may_deploy(user: CurrentUser, scope: str) -> None:
    """No personal scope: a deployed server has no credential of its
    own and its one door is the proxy, where every key of the
    organization's team reaches every server of the team (measured on
    v1.99.1: a member's own key lists the tools of another member's
    server, and a key's own list can only narrow the team's, an empty
    one not at all). The owner's settings would serve every member."""
    if scope not in (scopes.SCOPE_ORGANIZATION, scopes.SCOPE_PLATFORM):
        raise HTTPException(
            status_code=422,
            detail="A server is deployed for the organization or for the "
            "platform, not for one member",
        )
    if not scopes.can_create(user, scope):
        raise HTTPException(
            status_code=403,
            detail="Only a platform admin deploys a server for every "
            "organization"
            if scope == scopes.SCOPE_PLATFORM
            else "Only an organization admin deploys an MCP server",
        )


# --- routes ------------------------------------------------------------


@router.post(INSTANCES, response_model=McpServerSchema, status_code=201)
def deploy_server(
    body: McpDeployRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Deploy a catalog entry: an organization admin for the
    organization, a platform admin for every organization. A plain
    ``def``: no ``await`` stands between a flush and its commit (SQLite),
    and the Helm call runs to its end in this worker thread."""
    _may_deploy(user, body.scope)
    platform = body.scope == scopes.SCOPE_PLATFORM
    if not valid_name(body.name):
        raise HTTPException(
            status_code=400,
            detail="The name must be lower case letters, digits and _, "
            "start with a letter, and be at most 32 characters",
        )
    if body.approval is not None and body.approval not in APPROVALS:
        raise HTTPException(
            status_code=422,
            detail="approval must be one of " + ", ".join(APPROVALS),
        )
    entry = (
        db.query(McpCatalogEntry)
        .filter(
            McpCatalogEntry.name == body.catalog,
            McpCatalogEntry.status == STATUS_PUBLISHED,
        )
        .first()
    )
    # A draft reads like no entry: only a platform admin knows of it,
    # and nobody deploys an image that was not read.
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"No catalog entry named {body.catalog}"
        )
    plain, secret = _split(entry, body.settings)
    if registry._name_taken(db, user, body.name, body.scope):
        raise HTTPException(
            status_code=409, detail=f"MCP server '{body.name}' already exists"
        )
    mock = chat_mock_enabled()
    # Without the proxy a deployed server is of no use; and its team is
    # resolved before the first row change (``ensure_org_key`` commits).
    litellm = registry._require_litellm()
    try:
        if not platform:
            registry._team_id(litellm, db, user)
        if not mock:
            mcp_instances.proxy_selector()
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except ProxySelectorError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    controller = None if mock else _controller()

    instance_id = genid.uuid4()
    namespace = get_default_namespace()
    server = McpServer(
        id=genid.uuid4(),
        org_id=None if platform else user.org_id,
        owner_id=None,
        name=body.name,
        description=body.description,
        source=SOURCE_DEPLOYED,
        # Computed, never from input: http and inside the cluster, which
        # the URL rule refuses for every URL that somebody typed.
        url=mcp_instances.service_url(
            instance_id, namespace, entry.port, entry.path
        ),
        transport="http",
        credential_mode="none",
        allowed_tools=body.allowed_tools,
        approval=body.approval or "writes",
        enabled=True,
        tools_cache=[],
        # Not the column's default ("connected"): until the poller has
        # registered it, no request must select this server.
        status=STATUS_UNREACHABLE,
        checked_at=None,
    )
    instance = McpInstance(
        id=instance_id,
        server=server,
        catalog_id=entry.id,
        org_id=None if platform else user.org_id,
        owner_id=user.id,
        settings=plain,
        secret_settings=sorted(secret),
        image=entry.image,
        tag=entry.tag,
        startup=startup_of(entry),
        status=STATUS_PENDING,
        ready=False,
        launch=dict(_MOCK_LAUNCH) if mock else None,
    )
    db.add(server)
    try:
        # Before Helm on purpose, as for the other kinds: a release
        # without a row would be an orphan that nothing deletes.
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"MCP server '{body.name}' already exists"
        ) from None
    db.refresh(server)
    if mock:
        return registry._response(server, user)

    try:
        _write_secret(instance, secret)
        asyncio.run(controller.install(_spec(instance, entry)))
    except Exception as e:
        logger.exception("Could not deploy MCP server %s", body.name)
        mark_failed(db, instance, e)
        try:
            asyncio.run(controller.uninstall(instance.id))
        except Exception:
            logger.exception("Could not clean up after %s", body.name)
        raise HTTPException(
            status_code=500, detail=f"The server was not deployed: {e}"
        ) from e
    return registry._response(server, user)


@router.get(f"{INSTANCES}/{{id}}", response_model=McpInstanceSchema)
def get_instance(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    instance = _find_instance(db, id, user)
    if chat_mock_enabled():
        mock_advance(db, instance)
    return _instance_response(instance)


def _upgrade(db, instance, entry):
    """``helm upgrade`` with what the rows say now. The proxy
    registration stays: the URL does not change."""
    if chat_mock_enabled():
        return
    controller = _controller()
    mark_pending(instance)
    instance.ready = False
    db.commit()
    try:
        asyncio.run(controller.upgrade(_spec(instance, entry)))
    except Exception as e:
        logger.exception("Could not upgrade MCP server %s", instance.id)
        # The stored settings are the new ones: Helm may have applied
        # them, and the next upgrade must not render the old ones back.
        mark_failed(db, instance, e)
        raise HTTPException(
            status_code=500, detail=f"The change was not applied: {e}"
        ) from e


@router.put(f"{INSTANCES}/{{id}}/settings", response_model=McpInstanceSchema)
def update_settings(
    id: uuid.UUID,
    body: McpInstanceSettingsRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Replace the settings and roll the pod; the way to rotate an
    upstream token, and to repair a Failed server's wrong setting. A
    secret that is left out keeps its value."""
    instance = _find_instance_to_change(db, id, user)
    entry = instance.catalog
    schema = instance.startup.get("schema") or []
    kept = frozenset(instance.secret_settings or [])
    try:
        plain, given_secret = split_settings(
            schema, body.settings, kept_secrets=kept
        )
    except SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    stored = (
        {}
        if chat_mock_enabled()
        else get_secret_store().read_all(
            get_default_namespace(), mcp_instances.env_secret_name(instance.id)
        )
        or {}
    )
    known = {s["name"] for s in schema if s["secret"]}
    secret = {k: v for k, v in stored.items() if k in known}
    secret.update(given_secret)
    # The Secret before the row: a row that names a secret which was
    # never written would let the next change skip a required value.
    if not chat_mock_enabled():
        _write_secret(instance, secret)
    instance.settings = plain
    instance.secret_settings = sorted(set(secret) | (kept & known))
    db.commit()
    _upgrade(db, instance, entry)
    db.refresh(instance)
    return _instance_response(instance)


@router.post(f"{INSTANCES}/{{id}}/upgrade", response_model=McpInstanceSchema)
def upgrade_image(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Move the instance to the catalog entry's current image. Never by
    itself: a running server changes only when an admin says so."""
    instance = _find_instance_to_change(db, id, user)
    entry = instance.catalog
    if entry.status != STATUS_PUBLISHED:
        raise HTTPException(
            status_code=409,
            detail="The catalog entry is not published; there is no "
            "reviewed image to move to",
        )
    # The one place a running server takes over the entry's start-up.
    # The URL the proxy knows does not move with it: a new port or path
    # would need a new registration, so such an entry is refused.
    new = startup_of(entry)
    if (new["port"], new["path"]) != (
        instance.startup["port"],
        instance.startup["path"],
    ):
        raise HTTPException(
            status_code=409,
            detail="The entry's port or path has changed. Delete the "
            "server and deploy it again",
        )
    # Settings the new schema does not know would not render.
    names = {s["name"] for s in new["schema"]}
    instance.settings = {
        k: v for k, v in (instance.settings or {}).items() if k in names
    }
    instance.image, instance.tag, instance.startup = (
        entry.image,
        entry.tag,
        new,
    )
    db.commit()
    _upgrade(db, instance, entry)
    db.refresh(instance)
    return _instance_response(instance)


def _admins_read_logs(user: CurrentUser, row, label: str) -> None:
    """Every member uses a deployed server, and a server can log the
    arguments of the calls it gets: a member must not read there what
    another member asked. Events say nothing of the calls, so they stay
    with everybody who sees the server."""
    if not scopes.can_change(user, row.server):
        platform = row.server.org_id is None
        raise HTTPException(
            status_code=403,
            detail=f"Only {'a platform' if platform else 'an organization'} "
            "admin reads the logs of an MCP server: they can show what "
            "other members asked",
        )


def _everybody_who_sees_it(user: CurrentUser, row, label: str) -> None:
    """``_find_instance`` has decided it (``scopes.can_see``)."""


MCP_INSTANCE_KIND = InstanceKind(
    label="MCP server",
    find=_find_instance,
    authorize_read=_everybody_who_sees_it,
    authorize_write=_may_change,
    make_controller=lambda db, row: McpServerController(),
    namespace=lambda controller, row: controller.namespace,
    pod_labels=lambda db, controller, row: controller.get_pod_labels(row),
    restart=True,
    response_model=McpInstanceStateSchema,
    authorize_logs=_admins_read_logs,
)
add_inspection_routes(router, INSTANCES, MCP_INSTANCE_KIND)


# --- delete (called by the registry's one delete route) ---------------


def remove_workload(db: Session, server: McpServer) -> None:
    """The release and the Secret of a deployed server, after the proxy
    accepted the delete. A missing release is fine; another Helm error
    stops the delete (500), except on a Failed instance, which must
    stay deletable."""
    instance = server.instance
    if instance is None or chat_mock_enabled():
        return
    failed = instance.status == STATUS_FAILED
    try:
        asyncio.run(_controller().uninstall(instance.id))
        get_secret_store().delete(
            get_default_namespace(), mcp_instances.env_secret_name(instance.id)
        )
    except HTTPException:
        if not failed:
            raise
        logger.exception("Kubernetes is unreachable; deleting %s", server.name)
    except Exception as e:
        if not failed:
            raise HTTPException(
                status_code=500,
                detail=f"The server stays: it was not removed ({e})",
            ) from e
        logger.exception("Could not uninstall %s; deleting it", server.name)


# --- the poller --------------------------------------------------------


def _store_pods(db: Session, instance: McpInstance, pods) -> None:
    # Read first: ``apply_pod_status`` puts its own (unstored) value on
    # ``launch``, which here is a column.
    stored = (instance.ready, instance.launch)
    apply_pod_status(db, instance, pods)
    launch = pods.launch._asdict() if pods.launch is not None else None
    if instance.status == STATUS_FAILED or pods.ready:
        launch = None
    instance.launch = stored[1]
    if stored != (bool(pods.ready), launch):
        instance.ready = bool(pods.ready)
        instance.launch = launch
        db.commit()


def _register(db: Session, litellm, instance: McpInstance) -> None:
    """Registration, team permission and the first discovery; all three,
    then ONE commit. After any failure nothing is committed and the next
    tick starts again, which the chosen ``server_id`` makes safe."""
    server = instance.server
    alias = litellm_alias(server.id, server.name)
    # A platform server is for every organization's key, and no team's
    # list names it (as for a remote one, ``api/mcp.py``).
    platform = server.org_id is None
    team_id = (
        None
        if platform
        else registration.team_id_for_org(litellm, db, server.org_id)
    )
    body = registration.server_body(
        alias,
        server.url,
        server.transport,
        None,
        # As they are NOW: an admin can change them while the pod starts,
        # and a PATCH skips the proxy while there is no registration.
        server.allowed_tools,
        server.description,
        all_keys=platform,
        server_id=str(server.id),
    )
    # The connection test first: the readiness probe is a TCP check, so
    # "ready" does not say that the endpoint answers, and a registration
    # with nothing behind it is what the next steps would have to undo.
    tools = litellm.list_mcp_tools(
        registration.server_body("discover", server.url, server.transport)
    )
    registered = registration.register_once(litellm, body)
    server.litellm_server_id = registered
    db.flush()
    if not platform:
        registration.sync_team_for_org(litellm, db, server.org_id, team_id)
    server.tools_cache = [tool_summary(t) for t in tools]
    server.status = STATUS_CONNECTED
    server.checked_at = datetime.now()
    instance.registered_at = datetime.now()
    instance.ready_since = None
    instance.last_error = None
    instance.last_error_at = None
    db.commit()


def poll_instance(db: Session, litellm, controller, instance: McpInstance):
    """One instance, one tick."""
    server = instance.server
    pods = get_pod_status_and_readiness(
        controller.namespace, controller.get_pod_labels(instance)
    )
    _store_pods(db, instance, pods)
    if instance.registered_at is not None:
        # The URL did not change, so the proxy is not told: only the
        # platform's own selection reads this.
        wanted = STATUS_CONNECTED if instance.ready else STATUS_UNREACHABLE
        if server.status != wanted:
            server.status = wanted
            db.commit()
        if instance.ready and not server.tools_cache and litellm is not None:
            tools = litellm.list_mcp_tools(
                registration.server_body(
                    "discover", server.url, server.transport
                )
            )
            server.tools_cache = [tool_summary(t) for t in tools]
            db.commit()
        return
    if not instance.ready or not server.enabled or litellm is None:
        return
    if instance.ready_since is None:
        instance.ready_since = datetime.now()
        db.commit()
    try:
        _register(db, litellm, instance)
    except LiteLLMError as e:
        db.rollback()
        logger.info("MCP server %s is not registered yet: %s", server.name, e)
        since = instance.ready_since or datetime.now()
        if datetime.now() - since > UNREACHABLE_AFTER:
            instance.last_error = (
                "The pod is ready, but the proxy cannot reach it. Check the "
                "network policy's selector (AIOPS_LITELLM_POD_LABELS) and, "
                "with litellm.egressPolicy, its allowNamespaces. Last "
                f"answer: {e}"
            )[:4000]
            instance.last_error_at = datetime.now()
            db.commit()


def update_all_mcp_instances(db: Session) -> None:
    """The scheduler's job. Its own query, and not ``refresh_stale``:
    that one leaves Running rows out, so a pod that died later, or a
    registration that failed on the tick that made the row Running,
    would never be seen again. One controller for the tick."""
    try:
        instances = (
            db.query(McpInstance)
            .options(joinedload(McpInstance.server))
            .filter(
                McpInstance.status.is_(None)
                | (McpInstance.status != STATUS_STOPPED)
            )
            .all()
        )
        if not instances:
            return
        controller = McpServerController()
        litellm = registry.litellm_client()
        for instance in instances:
            try:
                poll_instance(db, litellm, controller, instance)
            except Exception:
                db.rollback()
                logger.exception("Could not poll MCP server %s", instance.id)
    except Exception:
        logger.exception("Could not poll the MCP servers")
    finally:
        db.close()
