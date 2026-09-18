import json
from datetime import UTC, datetime
from unittest import mock

import pytest
from pydantic import ValidationError

from controller import NotebooksController
from schemas import NotebookCreateSchema, NotebookInstanceSchema
from schemas.notebook import NOTEBOOK_NAME_MAX_LENGTH


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


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("has space", id="space"),
        pytest.param("Upper", id="uppercase"),
        pytest.param("a" * 64, id="64-chars"),
        pytest.param("a" * (NOTEBOOK_NAME_MAX_LENGTH + 1), id="too-long"),
        pytest.param("-leading", id="leading-dash"),
        pytest.param("trailing-", id="trailing-dash"),
        pytest.param("under_score", id="underscore"),
        pytest.param("", id="empty"),
    ],
)
def test_notebook_create_schema_rejects_invalid_names(name):
    with pytest.raises(ValidationError) as excinfo:
        NotebookCreateSchema(name=name, type="vscode", nvidia_gpu=False)
    errors = excinfo.value.errors()
    assert errors[0]["loc"] == ("name",)
    assert str(NOTEBOOK_NAME_MAX_LENGTH) in errors[0]["msg"]


@pytest.mark.parametrize(
    "name", ["nb", "a" * NOTEBOOK_NAME_MAX_LENGTH, "n1-2"]
)
def test_notebook_create_schema_accepts_valid_names(name):
    instance = NotebookCreateSchema(name=name, type="vscode", nvidia_gpu=False)
    assert instance.name == name


def test_notebook_create_schema_name_keeps_release_prefix():
    """The 41-character cut must never eat into the unique release prefix."""
    controller = NotebooksController(core_v1_api=mock.Mock())
    instance = NotebookCreateSchema(
        name="a" * NOTEBOOK_NAME_MAX_LENGTH, type="vscode", nvidia_gpu=False
    )
    release = controller._get_release_name(instance)
    service = controller.get_service_name(instance)
    assert len(release) <= 41
    assert len(service) <= 41
    assert service.startswith(release)


def test_notebook_response_schema_keeps_existing_long_names():
    # Rows created before the validator must still serialize.
    instance = NotebookInstanceSchema(
        name="Existing Name " + "x" * 60, type="vscode", nvidia_gpu=False
    )
    assert instance.name.startswith("Existing Name")


def test_notebook_namespace_defaults_to_the_platform_namespace(monkeypatch):
    # The chart runs the backend with AIOPS_NAMESPACE set to the release
    # namespace, where the shared OIDC policy lives; a notebook created
    # without a namespace must land there, like every other instance.
    monkeypatch.setenv("AIOPS_NAMESPACE", "aiops-platform")
    created = NotebookCreateSchema(name="nb", type="jupyter", nvidia_gpu=False)
    assert created.namespace == "aiops-platform"

    monkeypatch.delenv("AIOPS_NAMESPACE")
    created = NotebookCreateSchema(name="nb", type="jupyter", nvidia_gpu=False)
    assert created.namespace == "ai-stack"
