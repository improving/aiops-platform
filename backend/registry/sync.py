"""The daily best-effort sync of published, source-backed catalog
entries. ``sync_published(db)`` re-fetches each row's source and
refreshes the fields a source can change without admin input, and
records (or clears) ``sync_error`` per row; it never raises, so one
source outage never stops the rest of the sync (``core.py`` schedules
it, ``api/registry.py`` reuses ``apply_sync_fields`` for the on-demand
``POST /{id}/sync``).
"""

from datetime import datetime

from logger import setup_logger
from models.models import STATUS_PUBLISHED, DBModel
from registry import sources
from registry.entry import RegistryEntry, SourceError

logger = setup_logger(__name__)


def apply_sync_fields(model: DBModel, entry: RegistryEntry) -> None:
    """The metadata a sync may update -- never ``name``/``description``,
    which an admin may have edited by hand after the import."""
    model.license = entry.license
    model.parameters = entry.parameters
    model.context_length = entry.context_length
    model.size = entry.size
    model.formats = entry.formats
    model.tags = entry.tags
    model.raw = entry.raw
    model.synced_at = datetime.now()
    model.sync_error = None


def sync_published(db) -> None:
    """Every published row with a ``source_id``, re-fetched from its
    source; a row whose source is unreachable keeps its last known
    metadata and gets ``sync_error`` set instead of raising."""
    rows = (
        db.query(DBModel)
        .filter(
            DBModel.status == STATUS_PUBLISHED,
            DBModel.source_id.isnot(None),
        )
        .all()
    )
    for model in rows:
        try:
            entry = sources.fetch(model.source, model.source_id)
        except SourceError as e:
            logger.warning(
                "Registry sync failed for %s (%s/%s): %s",
                model.name,
                model.source,
                model.source_id,
                e.detail,
            )
            model.sync_error = e.detail
            db.commit()
            continue
        except Exception as e:  # pragma: no cover - defensive
            logger.exception(
                "Registry sync failed unexpectedly for %s", model.name
            )
            model.sync_error = str(e)
            db.commit()
            continue
        apply_sync_fields(model, entry)
        db.commit()
