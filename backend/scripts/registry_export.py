"""Write the current database's global catalog to
``raw_data/models.yaml`` (``uv run python scripts/registry_export.py``
from ``backend/``; the ``make registry-export`` target runs this
against the local Postgres of ``make backend``)."""

import sys
from pathlib import Path

# A flat application directory (pyproject.toml: package = false), not an
# installed package, so the backend root is not on sys.path by default
# when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import get_db_direct  # noqa: E402
from paths import RAW_DATA_DIR  # noqa: E402
from registry.export import write_registry  # noqa: E402


def main() -> None:
    db = get_db_direct()
    try:
        write_registry(db, RAW_DATA_DIR / "models.yaml")
    finally:
        db.close()


if __name__ == "__main__":
    main()
