"""Run the Alembic migrations from the app.

The CLI equivalent is ``uv run alembic upgrade head`` from ``backend/``
(``make db-migrate``).
"""

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

from logger import setup_logger
from paths import BACKEND_DIR

logger = setup_logger(__name__)

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# The revision that matches the schema the pre-Alembic code created
# with ``Base.metadata.create_all``.
BASELINE_REVISION = "0001"

# A table every pre-Alembic database has.
_SENTINEL_TABLE = "models"


def alembic_config(connection: Connection | None = None) -> Config:
    """The Alembic config; with ``connection`` env.py uses it instead
    of opening its own engine."""
    config = Config(str(ALEMBIC_INI))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade_to_head(engine: Engine) -> None:
    """Bring ``engine`` to the latest revision.

    A database created by the pre-Alembic code has the baseline tables
    but no revision; it is stamped ``0001`` first so ``upgrade`` starts
    from there instead of creating the tables again.
    """
    with engine.begin() as connection:
        config = alembic_config(connection)
        current = MigrationContext.configure(connection).get_current_revision()
        if current is None and inspect(connection).has_table(_SENTINEL_TABLE):
            logger.info(
                "Database predates Alembic, stamping %s", BASELINE_REVISION
            )
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
