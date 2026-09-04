import json
from datetime import UTC, datetime

from schemas import NotebookInstanceSchema


def test_notebook_schema_serializes_datetimes_as_isoformat():
    created = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    instance = NotebookInstanceSchema(
        name="nb",
        type="jupyter",
        framework="pytorch",
        nvidia_gpu=False,
        created_at=created,
    )
    dumped = json.loads(instance.model_dump_json())
    assert dumped["created_at"] == created.isoformat()
    assert dumped["updated_at"] is None
    # Python-mode dumps keep the datetime object.
    assert instance.model_dump()["created_at"] == created
