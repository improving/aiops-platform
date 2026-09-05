"""Export the global registry to a reviewable YAML file
(``raw_data/models.yaml``), the seed ``db/db.py`` ``load_models`` reads.

Only the global catalog (``org_id`` NULL) is exported: org-scoped rows
are per-deployment additions, not something that travels through a pull
request. ``raw``, ``synced_at``, ``sync_error``, ids and ``org_id`` are
dropped -- they are either derived (``raw``, sync bookkeeping) or
meaningless outside one database (ids).
"""

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from models.models import DBModel

YAML_VERSION = 1


def _serving_option_entry(option) -> dict:
    return {
        "engine": option.engine,
        "reference": option.reference,
        "default_args": option.default_args,
    }


def _model_entry(model: DBModel) -> dict:
    # A stable key order, sorted by engine, so re-exporting the same
    # data produces the same bytes and reviews stay small.
    options = sorted(model.serving_options, key=lambda o: o.engine)
    return {
        "name": model.name,
        "model_id": model.modelId,
        "source": model.source,
        "source_id": model.source_id,
        "description": model.description,
        "category": model.category,
        "subcategory": model.subcategory,
        "size": model.size,
        "license": model.license,
        "parameters": model.parameters,
        "context_length": model.context_length,
        "capabilities": list(model.capabilities or []),
        "formats": list(model.formats or []),
        "tags": list(model.tags or []),
        "status": model.status,
        "serving_options": [_serving_option_entry(o) for o in options],
    }


def export_registry(db: Session) -> str:
    """The global catalog (``org_id`` NULL) as YAML text, sorted by
    source, then source_id, then name."""
    rows = db.query(DBModel).filter(DBModel.org_id.is_(None)).all()
    rows.sort(key=lambda m: (m.source or "", m.source_id or "", m.name or ""))
    document = {
        "version": YAML_VERSION,
        "models": [_model_entry(m) for m in rows],
    }
    return yaml.dump(
        document,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def write_registry(db: Session, path: Path) -> None:
    Path(path).write_text(export_registry(db), encoding="utf-8")
