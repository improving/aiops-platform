"""Row lookup by the last eight hex characters of a UUID (the ``id8`` in
gateway hostnames and LiteLLM target names)."""

from sqlalchemy import String, cast


def find_by_id8(db, model, id8_value: str):
    return (
        db.query(model)
        .filter(cast(model.id, String).like(f"%{id8_value}"))
        .first()
    )
