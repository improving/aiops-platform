import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api import finetune
from api.audit import router as audit_router
from api.authz import router as authz_router
from api.chat import router as chat_router
from api.config import router as config_router
from api.credentials import router as credentials_router
from api.engines import router as engines_router
from api.hosts import router as hosts_router
from api.inference_instance import router as inference_instance_router
from api.inference_operations import router as inference_operations_router
from api.inference_status import update_all_inference_instance_endpoints
from api.model_adapters import router as model_adapters_router
from api.models import router as models_router
from api.notebooks import router as notebooks_router
from api.notebooks import update_all_notebook_instance_endpoints
from api.organizations import router as organizations_router
from api.providers import router as providers_router
from api.registry import router as registry_router
from api.tokens import router as tokens_router
from api.usage import router as usage_router
from api.vectordb import router as vectordb_router
from api.vectordb_instance import router as vectordb_instance_router
from api.vectordb_instance import update_all_vectordb_instance_endpoints
from audit.middleware import AuditMiddleware
from auth.current_user import CurrentUser, require_platform_admin
from auth.settings import MODE_DISABLED, check_auth_settings
from db.database import get_db, get_db_direct, get_engine
from db.db import init_db, refresh_db, reload_data
from logger import setup_logger
from registry.sync import sync_published

logger = setup_logger(__name__)

SCHEDULER_INTERVAL_SECONDS = 5
SCHEDULED_JOBS = (
    update_all_inference_instance_endpoints,
    update_all_notebook_instance_endpoints,
    update_all_vectordb_instance_endpoints,
)

# The daily registry sync (registry/sync.py): re-fetches every
# published, source-backed catalog entry, best effort. 0 disables it;
# TEST_MODE never schedules any job (build_scheduler is only called
# outside TEST_MODE, see create_app's lifespan).
REGISTRY_SYNC_INTERVAL_ENV = "REGISTRY_SYNC_INTERVAL_SECONDS"
DEFAULT_REGISTRY_SYNC_INTERVAL_SECONDS = 24 * 60 * 60


def registry_sync_interval_seconds() -> int:
    raw = os.environ.get(REGISTRY_SYNC_INTERVAL_ENV, "").strip()
    if not raw:
        return DEFAULT_REGISTRY_SYNC_INTERVAL_SECONDS
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not an integer, using the default",
            REGISTRY_SYNC_INTERVAL_ENV,
            raw,
        )
        return DEFAULT_REGISTRY_SYNC_INTERVAL_SECONDS


def is_test_mode() -> bool:
    return os.environ.get("TEST_MODE", "false").lower() == "true"


def _run_with_own_session(
    job: Callable[[Session], None],
) -> Callable[[], None]:
    """Give each scheduled run a fresh session.

    The jobs run in the scheduler's thread pool, so sharing one Session
    between them (and with the request handlers) is not safe and ends in
    ``ResourceClosedError`` once a connection is closed under another job.
    """

    def run() -> None:
        db = get_db_direct()
        try:
            job(db)
        finally:
            db.close()

    run.__name__ = job.__name__
    return run


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    for job in SCHEDULED_JOBS:
        scheduler.add_job(
            _run_with_own_session(job),
            trigger="interval",
            seconds=SCHEDULER_INTERVAL_SECONDS,
            id=job.__name__,
        )
    sync_interval = registry_sync_interval_seconds()
    if sync_interval > 0:
        scheduler.add_job(
            _run_with_own_session(sync_published),
            trigger="interval",
            seconds=sync_interval,
            id=sync_published.__name__,
        )
    return scheduler


def create_app(setup_db: bool = True):
    # Fail at startup on a configuration that cannot work; the JWKS itself
    # is fetched lazily on the first request.
    auth = check_auth_settings(is_test_mode())
    if auth.mode == MODE_DISABLED:
        logger.warning(
            "AUTH_MODE=disabled: every request runs as the dev admin"
        )

    engine = get_engine()
    db = get_db_direct()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # AsyncIOScheduler.start() needs a running event loop, so the
        # scheduler lives in the lifespan and not in create_app().
        if is_test_mode():
            logger.info("TEST_MODE is set, the endpoint scheduler is off")
            yield
            return

        scheduler = build_scheduler()
        for job in scheduler.get_jobs():
            logger.info("Job: %s", job)
        logger.info(
            "Starting scheduler with %d jobs", len(scheduler.get_jobs())
        )
        scheduler.start()
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            app.state.scheduler = None

    _app = FastAPI(lifespan=lifespan)

    # Include the API routes
    _app.include_router(models_router, tags=["models"])
    _app.include_router(engines_router, tags=["engines"])
    _app.include_router(inference_instance_router, tags=["inference_instance"])
    _app.include_router(
        inference_operations_router, tags=["inference_instance"]
    )
    _app.include_router(hosts_router, tags=["hosts"])
    _app.include_router(vectordb_router, tags=["vectordb"])
    _app.include_router(vectordb_instance_router, tags=["vectordb_instance"])
    _app.include_router(notebooks_router, tags=["notebooks"])
    _app.include_router(model_adapters_router, tags=["model_adapters"])
    _app.include_router(finetune.router, tags=["finetune"])
    _app.include_router(authz_router, tags=["authz"])
    _app.include_router(credentials_router, tags=["credentials"])
    _app.include_router(chat_router, tags=["chat"])
    _app.include_router(organizations_router, tags=["organizations"])
    _app.include_router(usage_router, tags=["organizations"])
    _app.include_router(providers_router, tags=["providers"])
    _app.include_router(registry_router, tags=["registry"])
    _app.include_router(audit_router, tags=["audit"])
    _app.include_router(tokens_router, tags=["tokens"])
    _app.include_router(config_router, tags=["config"])

    # The outermost middleware in this app's own stack, wrapping every
    # route including the utility endpoints; Starlette's own
    # ServerErrorMiddleware sits outside it and would otherwise render an
    # unhandled exception's 500 with no X-Request-ID, so AuditMiddleware
    # sends that one response itself before re-raising.
    _app.add_middleware(AuditMiddleware)

    @_app.post("/reload-data", tags=["utility"])
    async def reload_data_endpoint(
        db: Session = Depends(get_db),
        user: CurrentUser = Depends(require_platform_admin),
    ):
        reload_data(db)
        return {"message": "Data reloaded successfully"}

    @_app.post("/refresh-db", tags=["utility"])
    async def refresh_db_endpoint(
        db: Session = Depends(get_db),
        engine: Engine = Depends(get_engine),
        user: CurrentUser = Depends(require_platform_admin),
    ):
        refresh_db(db, engine)
        return {"message": "Data refreshed successfully"}

    @_app.get("/health", tags=["utility"])
    async def health_endpoint():
        return {"message": "OK"}

    if setup_db:
        init_db(db, engine)

    return _app
