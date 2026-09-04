from unittest import mock

import pytest
import yaml
from fastapi.testclient import TestClient
from pyhelm3.errors import ReleaseNotFoundError

from controller import NotebooksController, VectorDBController, get_controller
from controller.base_controller import ChartMetadataError, get_chart
from controller.finetune_controller import FinetuneController
from core import create_app
from schemas import (
    EngineChartsSchema,
    EngineSchema,
    InferenceInstanceConfigParamsSchema,
    InferenceInstanceSchema,
    ModelSchema,
    NotebookInstanceSchema,
    VectorDBInstanceSchema,
    VectorDBSchema,
)
from utils import genid


def test_controller():
    for engine_name in ["huggingface", "nim", "vllm", "opea"]:
        controller = get_controller(engine_name, core_v1_api=mock.Mock())
        assert controller is not None


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [(None, "ai-stack"), ("custom-ns", "custom-ns")],
)
def test_controller_namespace_env_override(monkeypatch, env_value, expected):
    if env_value is None:
        monkeypatch.delenv("AIOPS_NAMESPACE", raising=False)
    else:
        monkeypatch.setenv("AIOPS_NAMESPACE", env_value)
    assert (
        get_controller("vllm", core_v1_api=mock.Mock()).namespace == expected
    )
    assert VectorDBController(core_v1_api=mock.Mock()).namespace == expected
    assert FinetuneController().namespace == expected
    # An explicit argument still wins.
    explicit = VectorDBController(namespace="given", core_v1_api=mock.Mock())
    assert explicit.namespace == "given"


def test_vectordb_base_context_service_type():
    controller = VectorDBController(core_v1_api=mock.Mock())
    vectordb = VectorDBSchema(
        id=genid.uuid4(), name="qdrant", chart_name="qdrant", chart_repo="r"
    )
    default = VectorDBInstanceSchema(vectorDB=vectordb)
    assert controller._get_base_context(default) == {
        "service_type": "LoadBalancer"
    }
    no_key = VectorDBInstanceSchema(vectorDB=vectordb, configParams={"x": 1})
    assert controller._get_base_context(no_key) == {
        "service_type": "LoadBalancer"
    }
    explicit = VectorDBInstanceSchema(
        vectorDB=vectordb, configParams={"serviceType": "ClusterIP"}
    )
    assert controller._get_base_context(explicit) == {
        "service_type": "ClusterIP"
    }


@pytest.mark.asyncio
async def test_model_controller_helm_values(snapshot):  # pylint: disable=R0914
    app = create_app()
    client = TestClient(app)
    engines = client.get("/v1alpha1/engines").json()
    models = client.get("/v1alpha1/models").json()
    assert len(models) > 0
    assert len(engines) > 0

    # load list of models in modelschema
    model_schemas = [ModelSchema(**model) for model in models]

    # load list of engines in engine schema
    engine_schemas_map = {
        engine["name"].lower(): EngineSchema(**engine) for engine in engines
    }

    # get model schema for model id
    model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    model_schema = next(
        (model for model in model_schemas if model.modelId == model_id), None
    )
    if model_schema is None:
        raise ValueError(f"Model with id {model_id} not found")

    # build map of engine schemas
    engineChartMaps = {
        "huggingface": {
            "chart_repo": "https://infracloudio.github.io/charts",
            "chart_name": "text-generation-inference",
            "chart_type": "llm",
        },
        "vllm": {
            "chart_repo": "https://infracloudio.github.io/charts",
            "chart_name": "vllm",
            "chart_type": "llm",
        },
        "nim": {
            "chart_repo": "https://helm.ngc.nvidia.com/nim/charts/",
            "chart_name": "nim-llm-1.1.2.tgz",
            "chart_type": "llm",
        },
    }
    for engine_name, engine_schema in engine_schemas_map.items():
        if engine_name == "opea":
            continue
        controller = get_controller(engine_name, core_v1_api=mock.Mock())
        assert controller is not None
        instance = InferenceInstanceSchema(
            id=genid.uuid4(),
            model=model_schema,
            engine=engine_schema,
            host="gpu-node-3",
            config=InferenceInstanceConfigParamsSchema(
                id=genid.uuid4(),
                maxInputLength=100,
                maxTokens=100,
                maxBatchPrefillTokens=100,
                maxBatchTotalTokens=100,
                quantization="test",
                image="test",
                lora_adapters=[],
            ),
        )
        engine_chart_map = engineChartMaps[engine_name]
        engine_chart = EngineChartsSchema(
            id=genid.uuid4(),
            engine=engine_name,
            chart_type=engine_chart_map["chart_type"],
            chart_repo=engine_chart_map["chart_repo"],
            chart_name=engine_chart_map["chart_name"],
        )
        values = await controller.prepare_helm_values(instance, engine_chart)
        values_yaml = yaml.dump(values)
        snapshot.assert_match(
            values_yaml, engine_name.lower() + "-values.yaml"
        )


@pytest.mark.asyncio
async def test_notebook_controller_helm_values(snapshot):
    controller = NotebooksController(core_v1_api=mock.Mock())
    test_data = [
        NotebookInstanceSchema(
            name="notebook-jupyter",
            type="jupyter",
            framework="pytorch",
            resources_cpu="0.5",
            resources_memory="1Gi",
            nvidia_gpu=False,
            storage_size="5Gi",
        ),
        NotebookInstanceSchema(
            name="notebook-vscode",
            type="vscode",
            framework="",
            resources_cpu="1",
            resources_memory="4Gi",
            nvidia_gpu=False,
            storage_size="5Gi",
        ),
        NotebookInstanceSchema(
            name="notebook-gpu",
            type="jupyter",
            framework="pytorch",
            resources_cpu="2",
            resources_memory="16Gi",
            nvidia_gpu=True,
            resources_gpu="2",
            storage_size="10Gi",
        ),
    ]
    for data in test_data:
        values = await controller.prepare_helm_values(data)
        values_yaml = yaml.dump(values)
        snapshot.assert_match(values_yaml, f"notebook-values-{data.name}.yaml")


@pytest.mark.asyncio
async def test_vectordb_controller_helm_values(snapshot):
    app = create_app()
    client = TestClient(app)
    vectordbs = client.get("/v1alpha1/vectordb").json()
    vector_db_schemas = [VectorDBSchema(**vectordb) for vectordb in vectordbs]
    controller = VectorDBController(core_v1_api=mock.Mock())
    assert controller is not None
    for vector_db_schema in vector_db_schemas:
        instance = VectorDBInstanceSchema(vectorDB=vector_db_schema)
        values = await controller.prepare_helm_values(instance)
        values_yaml = yaml.dump(values)
        snapshot.assert_match(
            values_yaml, f"vectordb-values-{vector_db_schema.chart_name}.yaml"
        )


MILVUS_CHART_METADATA = {
    "apiVersion": "v2",
    "name": "milvus",
    "version": "5.0.27",
    "appVersion": "2.6.9",
    "home": "https://milvus.io/",
    "maintainers": [
        # The upstream Chart.yaml has a bare hostname, which pyhelm3
        # rejects with "Input should be a valid URL".
        {"name": "contact", "email": "contact@milvus.io", "url": "milvus.io"}
    ],
    "sources": ["https://github.com/zilliztech/milvus"],
}


CHART_REPO = "https://charts.example.test"


def _helm_with_chart(metadata):
    helm = mock.Mock()
    helm._command.show_chart = mock.AsyncMock(return_value=metadata)
    return helm


@pytest.mark.asyncio
async def test_get_chart_tolerates_invalid_maintainer_url():
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    chart = await get_chart(
        helm, "milvus", repo="https://zilliztech.github.io/milvus-helm"
    )
    assert chart.ref == "milvus"
    assert str(chart.repo) == "https://zilliztech.github.io/milvus-helm"
    # install_or_upgrade_release uses the version to pin the chart.
    assert chart.metadata.version == "5.0.27"
    assert chart.metadata.name == "milvus"
    assert chart.metadata.maintainers == []
    helm._command.show_chart.assert_awaited_once_with(
        "milvus",
        devel=False,
        repo="https://zilliztech.github.io/milvus-helm",
        version=None,
    )


@pytest.mark.asyncio
async def test_get_chart_keeps_valid_metadata():
    metadata = {
        **MILVUS_CHART_METADATA,
        "maintainers": [{"name": "contact", "url": "https://milvus.io"}],
    }
    chart = await get_chart(
        _helm_with_chart(metadata), "milvus", repo=CHART_REPO
    )
    assert str(chart.metadata.maintainers[0].url) == "https://milvus.io/"
    assert str(chart.metadata.home) == "https://milvus.io/"


@pytest.mark.asyncio
async def test_get_chart_reports_broken_required_metadata():
    metadata = {**MILVUS_CHART_METADATA, "version": "not-semver"}
    with pytest.raises(
        ChartMetadataError, match=r"(?s)'milvus'.*metadata\.version"
    ):
        await get_chart(_helm_with_chart(metadata), "milvus", repo=CHART_REPO)


def _milvus_instance():
    vectordb = VectorDBSchema(
        id=genid.uuid4(),
        name="Milvus",
        chart_name="milvus",
        chart_repo="https://zilliztech.github.io/milvus-helm",
    )
    return VectorDBInstanceSchema(vectorDB=vectordb)


@pytest.mark.asyncio
async def test_vectordb_controller_installs_milvus_without_status_parsing():
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    helm._command.install_or_upgrade = mock.AsyncMock()
    controller = VectorDBController(
        namespace="ai-stack", core_v1_api=mock.Mock(), helm_client=helm
    )
    instance = _milvus_instance()
    await controller.install(instance)
    # The HelmClient wrapper parses the release status, which embeds the
    # same invalid metadata; the raw command must be used instead.
    helm.install_or_upgrade_release.assert_not_called()
    helm._command.install_or_upgrade.assert_awaited_once()
    args, kwargs = helm._command.install_or_upgrade.await_args
    assert args[0] == controller._get_release_name(instance)
    assert args[1] == "milvus"
    assert kwargs["version"] == "5.0.27"
    assert kwargs["namespace"] == "ai-stack"
    assert kwargs["create_namespace"] is True
    assert str(kwargs["repo"]) == "https://zilliztech.github.io/milvus-helm"


@pytest.mark.asyncio
async def test_vectordb_controller_uninstalls_without_status_parsing():
    helm = mock.Mock()
    helm._command.uninstall = mock.AsyncMock()
    controller = VectorDBController(
        namespace="ai-stack", core_v1_api=mock.Mock(), helm_client=helm
    )
    instance = _milvus_instance()
    await controller.uninstall(instance)
    helm.get_current_revision.assert_not_called()
    helm._command.uninstall.assert_awaited_once_with(
        controller._get_release_name(instance), namespace="ai-stack", wait=True
    )
    # A release that is already gone is not an error.
    helm._command.uninstall.side_effect = ReleaseNotFoundError(
        1, b"", b"Error: uninstall: Release not loaded: release: not found"
    )
    await controller.uninstall(instance)
