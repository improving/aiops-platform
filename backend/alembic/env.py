from logging.config import fileConfig

from alembic import context

import models  # noqa: F401  (fills Base.metadata)
from db.database import Base, setup_engine

config = context.config

# The app (db/migrate.py) passes its own connection and keeps its own
# logging; the CLI gets the logging from alembic.ini.
connection = config.attributes.get("connection")
if connection is None and config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things; batch mode recreates the
        # table there and is a plain ALTER on Postgres.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline (--sql) mode is not supported")

if connection is not None:
    run_migrations(connection)
else:
    with setup_engine().connect() as connection:
        run_migrations(connection)
