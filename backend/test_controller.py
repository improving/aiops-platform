import base64
import threading
import uuid
from unittest import mock

import pytest
import yaml
from fastapi.testclient import TestClient
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from pyhelm3.errors import ReleaseNotFoundError

from controller import NotebooksController, VectorDBController, get_controller
from controller.base_controller import (
    ChartMetadataError,
    Controller,
    HelmInstallError,
    get_chart,
)
from controller.finetune_controller import FinetuneController
from controller.vllm_controller import VLLMController
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
from utils import credentials, genid
from utils.gateway import ApiKeyPolicyError, OidcPolicyError
from utils.kubernetes_utils import PodStatus


def test_controller():
    for engine_name in ["huggingface", "nim", "vllm", "opea", "ollama"]:
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
    no_credential = {
        "service_type": "ClusterIP",
        "credential": None,
        "credential_secret_name": None,
    }
    default = VectorDBInstanceSchema(vectorDB=vectordb)
    assert controller._get_base_context(default) == no_credential
    no_key = VectorDBInstanceSchema(vectorDB=vectordb, configParams={"x": 1})
    assert controller._get_base_context(no_key) == no_credential
    explicit = VectorDBInstanceSchema(
        vectorDB=vectordb, configParams={"serviceType": "ClusterIP"}
    )
    assert controller._get_base_context(explicit) == no_credential
    assert controller._get_base_context(explicit, "s3cret") == {
        "service_type": "ClusterIP",
        "credential": "s3cret",
        "credential_secret_name": f"vdb-{explicit.id.hex[-8:]}-credentials",
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
        if engine_name in ("opea", "ollama"):
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
        # The seeded value is what the create endpoint stores under
        # TEST_MODE, so the rendered auth lines are stable.
        credential = credentials.generate_secret(seed=str(instance.id))
        values = await controller.prepare_helm_values(
            instance, credential=credential
        )
        values_yaml = yaml.dump(values)
        snapshot.assert_match(
            values_yaml, f"vectordb-values-{vector_db_schema.chart_name}.yaml"
        )


def _vectordb_instance(chart_name, chart_repo):
    vectordb = VectorDBSchema(
        id=genid.uuid4(),
        name=chart_name.capitalize(),
        chart_name=chart_name,
        chart_repo=chart_repo,
    )
    return VectorDBInstanceSchema(vectorDB=vectordb)


def _qdrant_instance():
    return _vectordb_instance("qdrant", "https://qdrant.github.io/qdrant-helm")


def _chromadb_instance():
    return _vectordb_instance(
        "chromadb", "https://infracloudio.github.io/charts"
    )


def _credential_secret(value):
    encoded = base64.b64encode(value.encode()).decode()
    return client.V1Secret(data={"api-key": encoded})


@pytest.mark.asyncio
async def test_vectordb_helm_values_qdrant_references_the_credential_secret():
    controller = VectorDBController(core_v1_api=mock.Mock())
    instance = _qdrant_instance()
    with_key = await controller.prepare_helm_values(
        instance, credential="s3cret-value"
    )
    assert with_key["apiKey"] == {
        "valueFrom": {
            "secretKeyRef": {
                "name": f"vdb-{instance.id.hex[-8:]}-credentials",
                "key": "api-key",
            }
        }
    }
    # The value itself never enters the Helm values.
    assert "s3cret-value" not in yaml.dump(with_key)
    without = await controller.prepare_helm_values(instance)
    assert "apiKey" not in without
    assert without["service"] == with_key["service"]


@pytest.mark.asyncio
async def test_vectordb_helm_values_milvus_enables_authorization():
    controller = VectorDBController(core_v1_api=mock.Mock())
    instance = _milvus_instance()
    with_key = await controller.prepare_helm_values(
        instance, credential="s3cret"
    )
    user_yaml = yaml.safe_load(with_key["extraConfigFiles"]["user.yaml"])
    assert user_yaml == {
        "common": {
            "security": {
                "authorizationEnabled": True,
                "defaultRootPassword": "s3cret",
            }
        }
    }
    assert await controller.prepare_helm_values(instance) is None


@pytest.mark.asyncio
async def test_vectordb_helm_values_chromadb_is_gateway_only():
    controller = VectorDBController(core_v1_api=mock.Mock())
    instance = _chromadb_instance()
    with_key = await controller.prepare_helm_values(
        instance, credential="s3cret-value"
    )
    assert with_key == await controller.prepare_helm_values(instance)
    assert "s3cret-value" not in yaml.dump(with_key)


@pytest.mark.asyncio
async def test_vectordb_controller_upgrade_reads_the_credential_secret():
    """An upgrade without an explicit credential keeps the auth values by
    reading the credentials Secret; a missing Secret means no auth."""
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    helm._command.install_or_upgrade = mock.AsyncMock()
    core = mock.Mock(spec=client.CoreV1Api)
    core.read_namespaced_secret.return_value = _credential_secret(
        "fr0m-s3cret"
    )
    controller = VectorDBController(
        namespace="ai-stack", core_v1_api=core, helm_client=helm
    )
    instance = _milvus_instance()

    await controller.upgrade(instance)

    core.read_namespaced_secret.assert_called_once_with(
        name=f"vdb-{instance.id.hex[-8:]}-credentials", namespace="ai-stack"
    )
    values = helm._command.install_or_upgrade.await_args.args[2]
    assert "fr0m-s3cret" in values["extraConfigFiles"]["user.yaml"]

    core.read_namespaced_secret.side_effect = ApiException(status=404)
    await controller.upgrade(instance)
    assert helm._command.install_or_upgrade.await_args.args[2] is None

    core.read_namespaced_secret.side_effect = ApiException(status=500)
    with pytest.raises(ApiException):
        await controller.upgrade(instance)


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


def _milvus_instance(vectordb_id=None):
    # A fixed vectordb_id keeps a test off the global genid counter that
    # the snapshot tests below depend on.
    vectordb = VectorDBSchema(
        id=vectordb_id or genid.uuid4(),
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


@pytest.mark.asyncio
async def test_vectordb_controller_install_fails_when_the_api_route_fails(
    monkeypatch,
):
    """The SDK "-api" route is strict too (#27): a database served with
    nothing checking the key is the same exposure as an unprotected
    dashboard, and Chroma has no auth of its own at all. The failure
    keeps its own type rather than being relabelled a Helm failure."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(shared_targets=["sso"])
    policy_get = api_instance.get_namespaced_custom_object.side_effect

    def get(group, version, namespace, plural, name):
        if plural == "httproutes" and name.endswith("-api"):
            raise ApiException(status=500)
        return policy_get(group, version, namespace, plural, name)

    api_instance.get_namespaced_custom_object.side_effect = get
    controller = VectorDBController(
        namespace="ai-stack",
        core_v1_api=core,
        api_instance=api_instance,
        helm_client=helm,
    )
    instance = _milvus_instance()

    release = controller._get_release_name(instance)

    with pytest.raises(ApiKeyPolicyError) as excinfo:
        await controller.install(instance)

    assert f"{release}-api" in str(excinfo.value)
    assert not isinstance(excinfo.value, HelmInstallError)
    helm._command.install_or_upgrade.assert_awaited_once()
    # The browser route was published AND protected before the SDK route
    # was attempted, so the failure never leaves a dashboard open.
    patched = api_instance.patch_namespaced_custom_object.call_args.args[5]
    assert _target_names(patched) == ["sso", release]
    # And it is left alone: it is protected, and the endpoint uninstalls
    # the release next. Sweeping it here would tear down a working
    # dashboard because of a failure on the other route.
    deletes = [
        (c.args[3], c.args[4])
        for c in api_instance.delete_namespaced_custom_object.call_args_list
    ]
    assert ("httproutes", release) not in deletes


@pytest.mark.asyncio
async def test_vectordb_controller_install_fails_when_the_browser_route_fails(
    monkeypatch,
):
    """The browser route is strict: when it cannot be created the install
    fails before the policy step, so the shared OIDC policy never gets a
    targetRef to a route that does not exist. The failure is not
    mislabeled as a Helm failure (should-fix 5's OidcPolicyError rule
    extended to route creation, not just the policy attach)."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(shared_targets=["sso"])
    policy_get = api_instance.get_namespaced_custom_object.side_effect

    def get(group, version, namespace, plural, name):
        if plural == "httproutes" and not name.endswith("-api"):
            raise ApiException(status=500)
        return policy_get(group, version, namespace, plural, name)

    api_instance.get_namespaced_custom_object.side_effect = get
    controller = VectorDBController(
        namespace="ai-stack",
        core_v1_api=core,
        api_instance=api_instance,
        helm_client=helm,
    )
    instance = _milvus_instance(vectordb_id=uuid.UUID(int=0x52))
    release = controller._get_release_name(instance)

    with pytest.raises(OidcPolicyError) as excinfo:
        await controller.install(instance)

    assert str(excinfo.value).startswith(
        f"HTTPRoute ai-stack/{release} could not be created"
    )
    api_instance.create_namespaced_custom_object.assert_not_called()
    api_instance.patch_namespaced_custom_object.assert_not_called()


@pytest.mark.asyncio
async def test_notebook_controller_install_fails_when_the_browser_route_fails(
    monkeypatch,
):
    """The NotebooksController counterpart: the browser route is strict,
    and a create failure must not be mislabeled as a Helm failure."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(
        {"apiVersion": "v2", "name": "kf-notebooks", "version": "0.1.0"}
    )
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(shared_targets=["sso"])
    api_instance.get_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    controller = NotebooksController(
        api_instance=api_instance, core_v1_api=core, helm=helm
    )
    instance = _notebook(notebook_id=uuid.UUID(int=0x53))
    release = controller._get_release_name(instance)

    with pytest.raises(OidcPolicyError) as excinfo:
        await controller.install(instance)

    assert str(excinfo.value).startswith(
        f"HTTPRoute {instance.namespace}/{release} could not be created"
    )
    api_instance.create_namespaced_custom_object.assert_not_called()
    api_instance.patch_namespaced_custom_object.assert_not_called()


@pytest.mark.asyncio
async def test_vectordb_controller_install_fails_closed_without_the_policy(
    monkeypatch,
):
    """The browser route cannot join the OIDC policy (here: the policy
    patch fails): the route is deleted again and the install raises, so
    the create endpoint marks the row Failed and uninstalls the release.
    A dashboard must never stay reachable without a login."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(shared_targets=["sso"])
    api_instance.patch_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    controller = VectorDBController(
        namespace="ai-stack",
        core_v1_api=core,
        api_instance=api_instance,
        helm_client=helm,
    )
    instance = _milvus_instance(vectordb_id=uuid.UUID(int=0x51))
    release = controller._get_release_name(instance)

    with pytest.raises(OidcPolicyError) as excinfo:
        await controller.install(instance, credential="s3cret")

    # Not wrapped as a Helm failure: Helm succeeded, the gateway refused.
    assert str(excinfo.value).startswith(
        f"HTTPRoute ai-stack/{release} could not join SecurityPolicy "
        f"{SHARED_OIDC}"
    )
    # Each route is created and protected as a pair, so the failure on
    # the browser pair means the SDK route is never published at all.
    routes = [
        r["metadata"]["name"] for r in _created(api_instance, "HTTPRoute")
    ]
    assert routes == [release]
    deletes = [
        (c.args[3], c.args[4])
        for c in api_instance.delete_namespaced_custom_object.call_args_list
    ]
    # The browser route is removed by protect_browser_route, and the
    # install's cleanup then sweeps for anything else.
    assert ("httproutes", release) in deletes
    assert _created(api_instance, "SecurityPolicy") == []


@pytest.mark.asyncio
async def test_notebook_controller_install_fails_closed_without_sso_route(
    monkeypatch,
):
    """No policy in the namespace and no sso callback route to build one
    from (an AIOPS_NAMESPACE where neither make auth-up nor the chart
    installed the policy): the notebook route is deleted again and the
    install raises with the policy named."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(
        {"apiVersion": "v2", "name": "kf-notebooks", "version": "0.1.0"}
    )
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(sso_route=False)
    controller = NotebooksController(
        api_instance=api_instance, core_v1_api=core, helm=helm
    )
    instance = _notebook()
    release = controller._get_release_name(instance)

    with pytest.raises(OidcPolicyError) as excinfo:
        await controller.install(instance)

    assert SHARED_OIDC in str(excinfo.value)
    assert "no sso HTTPRoute" in str(excinfo.value)
    assert _created(api_instance, "SecurityPolicy") == []
    assert _created(api_instance, "BackendTrafficPolicy") == []
    api_instance.delete_namespaced_custom_object.assert_called_once_with(
        "gateway.networking.k8s.io",
        "v1",
        instance.namespace,
        "httproutes",
        release,
    )


# --- Task 10: gateway policies per instance --------------------------------

SHARED_OIDC = "aiops-workloads-oidc"


def _gateway_mocks(
    *, secret_exists=False, shared_targets=None, sso_route=True
):
    """A CustomObjectsApi whose objects are all missing (404), except the
    shared OIDC policy when shared_targets is given and the sso callback
    HTTPRoute (which lets the policy be created from scratch), and a
    CoreV1Api whose Secrets exist or not and whose Services exist."""
    api_instance = mock.Mock(spec=client.CustomObjectsApi)

    def get(group, version, namespace, plural, name):
        if plural == "httproutes" and name == "sso" and sso_route:
            return {"metadata": {"name": "sso", "namespace": namespace}}
        if plural == "securitypolicies" and name == SHARED_OIDC:
            if shared_targets is None:
                raise ApiException(status=404)
            return {
                "metadata": {"name": SHARED_OIDC, "resourceVersion": "1"},
                "spec": {
                    "targetRefs": [
                        {
                            "group": "gateway.networking.k8s.io",
                            "kind": "HTTPRoute",
                            "name": n,
                        }
                        for n in shared_targets
                    ]
                },
            }
        if plural == "referencegrants":
            return {
                "spec": {
                    "from": [
                        {
                            "group": "gateway.envoyproxy.io",
                            "kind": "SecurityPolicy",
                            "namespace": "ai-stack",
                        }
                    ]
                }
            }
        raise ApiException(status=404)

    api_instance.get_namespaced_custom_object.side_effect = get
    core = mock.Mock(spec=client.CoreV1Api)
    if not secret_exists:
        core.read_namespaced_secret.side_effect = ApiException(status=404)
    return api_instance, core


def _created(api_instance, kind):
    return [
        c.args[4]
        for c in api_instance.create_namespaced_custom_object.call_args_list
        if c.args[4]["kind"] == kind
    ]


def _target_names(body):
    return [r["name"] for r in body["spec"]["targetRefs"]]


def _notebook(notebook_id=None):
    # A fixed notebook_id keeps a test off the global genid counter the
    # snapshot tests below depend on (see _milvus_instance); omitting the
    # kwarg entirely (rather than passing id=None) keeps the default
    # genid factory for every existing caller.
    extra = {"id": notebook_id} if notebook_id is not None else {}
    return NotebookInstanceSchema(
        name="t10-nb",
        type="jupyter",
        framework="pytorch",
        resources_cpu="0.5",
        resources_memory="1Gi",
        nvidia_gpu=False,
        storage_size="5Gi",
        **extra,
    )


@pytest.mark.asyncio
async def test_notebook_controller_install_protects_route(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(
        {"apiVersion": "v2", "name": "kf-notebooks", "version": "0.1.0"}
    )
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks()
    controller = NotebooksController(
        api_instance=api_instance, core_v1_api=core, helm=helm
    )
    instance = _notebook()
    release = controller._get_release_name(instance)

    await controller.install(instance)

    routes = _created(api_instance, "HTTPRoute")
    assert [r["metadata"]["name"] for r in routes] == [release]
    (policy,) = _created(api_instance, "SecurityPolicy")
    assert policy["metadata"]["name"] == SHARED_OIDC
    assert _target_names(policy) == ["sso", release]
    (traffic,) = _created(api_instance, "BackendTrafficPolicy")
    assert traffic["metadata"]["name"] == release
    assert _target_names(traffic) == [release]
    core.patch_namespaced_service.assert_not_called()


@pytest.mark.asyncio
async def test_notebook_controller_uninstall_removes_route_before_policies(
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = mock.Mock()
    helm._command.uninstall = mock.AsyncMock()
    instance = _notebook()
    controller = NotebooksController(
        api_instance=mock.Mock(), core_v1_api=mock.Mock(), helm=helm
    )
    release = controller._get_release_name(instance)
    api_instance, core = _gateway_mocks(shared_targets=["sso", release])
    controller.api_instance = api_instance

    manager = mock.Mock()
    manager.attach_mock(api_instance.delete_namespaced_custom_object, "delete")
    manager.attach_mock(api_instance.patch_namespaced_custom_object, "patch")

    await controller.uninstall(instance)

    steps = [
        (c[0], c.args[3] if c[0] == "delete" else c.args[4])
        for c in manager.mock_calls
    ]
    # The route goes first so a failed Helm uninstall never leaves a
    # route without its OIDC target (N5 of the PR 25 review).
    assert steps == [
        ("delete", "httproutes"),
        ("delete", "backendtrafficpolicies"),
        ("patch", SHARED_OIDC),
    ]
    patch_body = api_instance.patch_namespaced_custom_object.call_args.args[5]
    assert _target_names(patch_body) == ["sso"]


@pytest.mark.asyncio
async def test_vectordb_controller_install_policies(monkeypatch):
    """The browser route joins the shared OIDC policy; the SDK route gets
    its own API-key policy. The credential Secret is checked first (#27):
    a policy pointing at a Secret that is not there cannot enforce
    anything, so it would leave the route open in practice."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(secret_exists=True)
    controller = VectorDBController(
        namespace="ai-stack",
        core_v1_api=core,
        api_instance=api_instance,
        helm_client=helm,
    )
    instance = _milvus_instance()
    release = controller._get_release_name(instance)

    await controller.install(instance, credential="s3cret")

    values = helm._command.install_or_upgrade.await_args.args[2]
    assert "s3cret" in values["extraConfigFiles"]["user.yaml"]
    # The Secret backing the API-key policy is verified before the
    # policy is created.
    core.read_namespaced_secret.assert_called()
    routes = [
        r["metadata"]["name"] for r in _created(api_instance, "HTTPRoute")
    ]
    assert routes == [release, f"{release}-api"]
    policies = {
        p["metadata"]["name"]: p
        for p in _created(api_instance, "SecurityPolicy")
    }
    assert set(policies) == {SHARED_OIDC, f"{release}-api-apikey"}
    assert _target_names(policies[SHARED_OIDC]) == ["sso", release]
    apikey = policies[f"{release}-api-apikey"]
    assert _target_names(apikey) == [f"{release}-api"]
    assert apikey["spec"]["apiKeyAuth"]["credentialRefs"] == [
        {
            "kind": "Secret",
            "name": f"vdb-{instance.id.hex[-8:]}-apikey-auth",
        }
    ]
    assert apikey["spec"]["apiKeyAuth"]["sanitize"] is False
    assert _created(api_instance, "BackendTrafficPolicy") == []


@pytest.mark.asyncio
async def test_vectordb_controller_uninstall_removes_policies(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = mock.Mock()
    helm._command.uninstall = mock.AsyncMock()
    instance = _milvus_instance()
    controller = VectorDBController(
        namespace="ai-stack", core_v1_api=mock.Mock(), helm_client=helm
    )
    release = controller._get_release_name(instance)
    api_instance, _ = _gateway_mocks(shared_targets=["sso", release])
    controller.api_instance = api_instance

    await controller.uninstall(instance)

    deletes = [
        (c.args[3], c.args[4])
        for c in api_instance.delete_namespaced_custom_object.call_args_list
    ]
    assert deletes == [
        ("httproutes", release),
        ("httproutes", f"{release}-api"),
        ("securitypolicies", f"{release}-api-apikey"),
    ]
    patch_body = api_instance.patch_namespaced_custom_object.call_args.args[5]
    assert _target_names(patch_body) == ["sso"]


def _inference_instance_and_chart():
    model = ModelSchema(
        id=genid.uuid4(), name="test-model", category="llm", size=1
    )
    engine = EngineSchema(id=genid.uuid4(), name="vllm")
    instance = InferenceInstanceSchema(
        id=genid.uuid4(),
        model=model,
        engine=engine,
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
    chart = EngineChartsSchema(
        id=genid.uuid4(),
        engine="vllm",
        chart_repo="https://infracloudio.github.io/charts",
        chart_name="vllm",
        chart_type="llm",
    )
    return instance, chart


@pytest.mark.asyncio
@pytest.mark.parametrize("secret_exists", [False, True])
async def test_inference_controller_single_route_and_apikey_policy(
    monkeypatch, secret_exists
):
    """With the credential Secret in place the inf- route gets its
    API-key policy; without it the install fails closed (#27) and the
    route is removed, because no in-repo inference engine except vLLM
    checks a key of its own."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    instance, chart = _inference_instance_and_chart()
    helm = mock.Mock()
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(secret_exists=secret_exists)
    controller = get_controller(
        "vllm",
        namespace="ai-stack",
        api_instance=api_instance,
        core_v1_api=core,
        helm_client=helm,
    )
    # The engine chart row carries chart_version; the schema does not.
    controller._add_and_update_helm_repo = mock.AsyncMock(
        return_value=mock.Mock(
            ref="vllm", repo=chart.chart_repo, metadata=mock.Mock(version="1")
        )
    )
    release = controller._get_release_name(instance)

    if not secret_exists:
        with pytest.raises(ApiKeyPolicyError) as excinfo:
            await controller.install(instance, chart)
        assert "apikey-auth" in str(excinfo.value)
        assert not isinstance(excinfo.value, HelmInstallError)
        deleted = [
            (c.args[3], c.args[4])
            for c in api_instance.delete_namespaced_custom_object.call_args_list
        ]
        assert ("httproutes", release) in deleted
        assert _created(api_instance, "SecurityPolicy") == []
        return

    await controller.install(instance, chart)

    routes = _created(api_instance, "HTTPRoute")
    traffic = _created(api_instance, "BackendTrafficPolicy")
    assert [t["metadata"]["name"] for t in traffic] == [release]
    assert traffic[0]["spec"]["timeout"] == {
        "http": {"requestTimeout": "0s", "streamIdleTimeout": "10m"}
    }
    assert [r["metadata"]["name"] for r in routes] == [release]
    assert routes[0]["spec"]["hostnames"] == [
        f"inf-{instance.id.hex[-8:]}.127.0.0.1.nip.io"
    ]
    policies = _created(api_instance, "SecurityPolicy")
    (policy,) = policies
    assert policy["metadata"]["name"] == release
    assert _target_names(policy) == [release]
    assert "apiKeyAuth" in policy["spec"]
    assert "oidc" not in policy["spec"]

    helm._command.uninstall = mock.AsyncMock()
    await controller.uninstall(instance)
    deletes = [
        (c.args[3], c.args[4])
        for c in api_instance.delete_namespaced_custom_object.call_args_list
    ]
    # The route goes first: a policy briefly targeting a route that is
    # gone is harmless, a route outliving its API-key policy is not, and
    # this runs from a finally that also fires when the Helm uninstall
    # failed and the workload is still serving.
    assert deletes == [
        ("httproutes", release),
        ("backendtrafficpolicies", release),
        ("securitypolicies", release),
    ]


# --- Task 14: inference endpoint keys ---------------------------------------
#
# The SecurityPolicy on the "inf-<id8>" route (created via
# base_controller._ensure_gateway_routes -> protect_sdk_route) is already
# covered above by test_inference_controller_single_route_and_apikey_policy
# and by test_ensure_security_policy_apikey_body in test_gateway.py. What is
# new here is the credential itself: vLLM's rendered values reference it with
# a secretKeyRef (never the raw value), and the API stores/removes it around
# controller.install/uninstall.


def test_vllm_engine_context_carries_the_credential_reference():
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    context = controller._get_engine_specific_context(instance, chart)
    id8 = instance.id.hex[-8:]
    assert context["credential_secret_name"] == f"inf-{id8}-credentials"
    assert context["credential_secret_key"] == "api-key"


@pytest.mark.asyncio
async def test_vllm_rendered_values_reference_the_credential_secret():
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    values = await controller.prepare_helm_values(instance, chart)
    id8 = instance.id.hex[-8:]
    env_by_name = {e["name"]: e for e in values["env"]}
    assert env_by_name["VLLM_API_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": f"inf-{id8}-credentials",
        "key": "api-key",
    }
    # Never the raw value.
    assert "value" not in env_by_name["VLLM_API_KEY"]


# --- launching a vLLM instance on a cluster whose model cache is empty -------
#
# Measured on the lab's first GPU launch (2026-09-18): the pod downloads the
# weights on its first start, which took minutes, and four things were wrong.


@pytest.mark.asyncio
async def test_vllm_rendered_values_give_the_hub_library_its_token():
    # huggingface_hub reads HF_TOKEN only; with just HF_API_TOKEN set the
    # download ran anonymous (about 5 MB/s against 30 with the token) and a
    # gated model could not be fetched at all.
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    values = await controller.prepare_helm_values(instance, chart)
    env_by_name = {e["name"]: e for e in values["env"]}
    for name in ("HF_TOKEN", "HF_API_TOKEN"):
        assert env_by_name[name]["valueFrom"]["secretKeyRef"] == {
            "name": "hf-api-token",
            "key": "HF_API_TOKEN",
            # A public model needs no token: a platform without one must
            # still start the pod.
            "optional": True,
        }


@pytest.mark.asyncio
async def test_vllm_liveness_waits_for_a_first_start():
    # The chart has no startup probe, and the liveness probe killed the
    # container two minutes into a download the hub library does not
    # resume, forever. The delay only applies at container start: a server
    # that hangs later is still restarted, and readiness still gates traffic.
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    values = await controller.prepare_helm_values(instance, chart)
    # Two hours by default. Measured on the lab: a 10 GB model took 28
    # minutes on a slow evening and was ready 78 s before a 30 minute delay
    # ended. A kill restarts the download from zero, so a delay that is too
    # short is a loop nobody can leave, while a start that hangs is rare,
    # visible in the UI and one Restart away.
    assert values["livenessProbe"]["initialDelaySeconds"] == 7200
    assert values["readinessProbe"]["initialDelaySeconds"] == 30


@pytest.mark.asyncio
async def test_vllm_liveness_delay_is_configurable(monkeypatch):
    # Short again once the chart has a startup probe (charts/vllm 0.4.1),
    # or longer on a slower link: an operator's call, not a code change.
    monkeypatch.setenv("VLLM_LIVENESS_INITIAL_DELAY_SECONDS", "60")
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    values = await controller.prepare_helm_values(instance, chart)
    assert values["livenessProbe"]["initialDelaySeconds"] == 60

    monkeypatch.setenv("VLLM_LIVENESS_INITIAL_DELAY_SECONDS", "soon")
    values = await controller.prepare_helm_values(instance, chart)
    assert values["livenessProbe"]["initialDelaySeconds"] == 7200


@pytest.mark.asyncio
async def test_vllm_values_carry_a_startup_probe():
    # The chart renders it from 0.4.1 on and ignores it before: the first
    # start gets two hours, and liveness only begins once it succeeded.
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    values = await controller.prepare_helm_values(instance, chart)
    probe = values["startupProbe"]
    assert probe["httpGet"] == {"path": "/health", "port": "http"}
    assert probe["periodSeconds"] * probe["failureThreshold"] == 7200


@pytest.mark.asyncio
async def test_vllm_keeps_its_compile_cache_on_the_model_volume():
    # torch.compile artifacts next to the weights, so a restart or a second
    # launch of the model skips the compilation.
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    values = await controller.prepare_helm_values(instance, chart)
    env_by_name = {e["name"]: e for e in values["env"]}
    assert env_by_name["VLLM_CACHE_ROOT"]["value"] == "/model/.vllm-cache"


@pytest.mark.asyncio
async def test_vllm_install_writes_the_hub_token_secret_first(monkeypatch):
    # The rendered values reference the Secret, so install makes sure the
    # namespace and the Secret exist before Helm runs, like the TGI install.
    monkeypatch.setenv("HF_API_TOKEN", "hf_test")
    core_v1 = mock.Mock()
    controller = get_controller("vllm", core_v1_api=core_v1)
    order = []
    monkeypatch.setattr(
        controller, "create_ns_if_needed", lambda: order.append("namespace")
    )
    core_v1.create_namespaced_secret.side_effect = lambda namespace, body: (
        order.append(f"secret:{body.metadata.name}")
    )

    async def helm_install(self, instance, chart):
        order.append("helm")

    monkeypatch.setattr(Controller, "install", helm_install)
    instance, chart = _inference_instance_and_chart()
    await controller.install(instance, chart)
    assert order == ["namespace", "secret:hf-api-token", "helm"]
    secret = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    assert secret.string_data == {"HF_API_TOKEN": "hf_test"}


@pytest.mark.asyncio
async def test_a_rotated_hub_token_replaces_the_secret(monkeypatch):
    monkeypatch.setenv("HF_API_TOKEN", "hf_new")
    core_v1 = mock.Mock()
    core_v1.create_namespaced_secret.side_effect = ApiException(status=409)
    controller = get_controller("vllm", core_v1_api=core_v1)
    assert await controller._ensure_hf_api_token_secret() is True
    replaced = core_v1.replace_namespaced_secret.call_args.kwargs
    assert replaced["name"] == "hf-api-token"
    assert replaced["body"].string_data == {"HF_API_TOKEN": "hf_new"}


@pytest.mark.asyncio
async def test_vllm_install_needs_no_hub_token(monkeypatch):
    monkeypatch.delenv("HF_API_TOKEN", raising=False)
    core_v1 = mock.Mock()
    controller = get_controller("vllm", core_v1_api=core_v1)
    assert await controller._ensure_hf_api_token_secret() is False
    core_v1.create_namespaced_secret.assert_not_called()


def test_vllm_tracing_needs_a_collector(monkeypatch):
    # The old default pointed every traced instance at a Jaeger of the
    # retired lab; without TRACING_URL there is nowhere to send traces.
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    instance.config.enable_tracing = True
    monkeypatch.delenv("TRACING_URL", raising=False)
    context = controller._get_engine_specific_context(instance, chart)
    assert not any("otlp" in str(a) for a in context["args"])

    monkeypatch.setenv("TRACING_URL", "grpc://jaeger.example:4317")
    instance.config.args = None
    context = controller._get_engine_specific_context(instance, chart)
    assert any("grpc://jaeger.example:4317" in str(a) for a in context["args"])


def _seeded(client, kind, predicate):
    """The first row from a catalog endpoint matching predicate."""
    return next(
        row for row in client.get(f"/v1alpha1/{kind}").json() if predicate(row)
    )


@pytest.mark.asyncio
async def test_create_inference_instance_stores_and_delete_removes_credential(
    monkeypatch,
):
    """Task 14: create stores both credential Secrets before install runs;
    delete removes them after uninstall. The controller install/uninstall
    and the Kubernetes CoreV1 client are mocked, per backend/AGENTS.md."""
    monkeypatch.setenv("HF_API_TOKEN", "hf-test-token")
    app = create_app()
    client_ = TestClient(app)
    model = _seeded(client_, "models", lambda m: m["category"] == "llm")
    engine = _seeded(client_, "engines", lambda e: e["name"] == "vLLM")

    # get_controller is called from api.inference_instance (create,
    # delete) and api.inference_status (the list route's refresh).
    get_ctrl = mock.Mock()
    # The list route reads service_url for the response's clusterEndpoint,
    # which is typed str | None: a bare Mock fails response validation.
    get_ctrl.return_value.service_url.return_value = (
        "http://vllm-00000000.ai-stack.svc:80"
    )
    get_ctrl.return_value.workload_checks_api_key = True
    with (
        mock.patch("api.inference_instance.get_controller", get_ctrl),
        mock.patch("api.inference_status.get_controller", get_ctrl),
        mock.patch("utils.credentials.get_core_v1_client") as get_core_v1,
        mock.patch(
            "api.inference_status.get_pod_status_and_readiness",
            return_value=PodStatus(False, "Unknown"),
        ),
    ):
        controller = get_ctrl.return_value
        controller.namespace = "ai-stack"
        controller.install = mock.AsyncMock()
        controller.get_service_name.return_value = "svc"
        core_v1 = get_core_v1.return_value

        response = client_.post(
            "/v1alpha1/inferenceInstance",
            json={"model": model, "engine": engine},
        )
        assert response.status_code == 201, response.text
        instance_id = response.json()["id"]
        id8 = uuid.UUID(instance_id).hex[-8:]
        credential_name = f"inf-{id8}-credentials"
        apikey_name = f"inf-{id8}-apikey-auth"

        controller.install.assert_awaited_once()
        created = {
            c.kwargs["body"].metadata.name: c.kwargs["body"]
            for c in core_v1.create_namespaced_secret.call_args_list
        }
        assert set(created) == {credential_name, apikey_name}
        assert created[credential_name].metadata.namespace == "ai-stack"
        value = created[credential_name].string_data["api-key"]
        assert created[apikey_name].string_data == {instance_id: value}

        controller.uninstall = mock.AsyncMock()
        deleted_response = client_.delete(
            f"/v1alpha1/inferenceInstance/{instance_id}"
        )
        assert deleted_response.status_code == 200, deleted_response.text
        controller.uninstall.assert_awaited_once()
        deleted_names = {
            c.kwargs["name"]
            for c in core_v1.delete_namespaced_secret.call_args_list
        }
        assert deleted_names == {credential_name, apikey_name}
        remaining = {
            i["id"] for i in client_.get("/v1alpha1/inferenceInstance").json()
        }
        assert instance_id not in remaining


@pytest.mark.asyncio
async def test_create_inference_instance_keeps_the_row_on_install_failure(
    monkeypatch,
):
    monkeypatch.setenv("HF_API_TOKEN", "hf-test-token")
    app = create_app()
    client_ = TestClient(app)
    model = _seeded(client_, "models", lambda m: m["category"] == "llm")
    engine = _seeded(client_, "engines", lambda e: e["name"] == "vLLM")

    # get_controller is called from api.inference_instance (create,
    # delete) and api.inference_status (the list route's refresh).
    get_ctrl = mock.Mock()
    # The list route reads service_url for the response's clusterEndpoint,
    # which is typed str | None: a bare Mock fails response validation.
    get_ctrl.return_value.service_url.return_value = (
        "http://vllm-00000000.ai-stack.svc:80"
    )
    get_ctrl.return_value.workload_checks_api_key = True
    with (
        mock.patch("api.inference_instance.get_controller", get_ctrl),
        mock.patch("api.inference_status.get_controller", get_ctrl),
        mock.patch("utils.credentials.get_core_v1_client") as get_core_v1,
        mock.patch(
            "api.inference_status.get_pod_status_and_readiness",
            return_value=PodStatus(False, "Unknown"),
        ),
    ):
        controller = get_ctrl.return_value
        controller.namespace = "ai-stack"
        controller.get_pod_labels.return_value = (
            "app.kubernetes.io/instance=vllm-x,app.kubernetes.io/name=vllm"
        )
        controller.install = mock.AsyncMock(side_effect=RuntimeError("boom"))
        controller.uninstall = mock.AsyncMock()
        core_v1 = get_core_v1.return_value

        before = {
            i["id"] for i in client_.get("/v1alpha1/inferenceInstance").json()
        }
        response = client_.post(
            "/v1alpha1/inferenceInstance",
            json={"model": model, "engine": engine},
        )
        assert response.status_code == 500

        created = {
            c.kwargs["body"].metadata.name
            for c in core_v1.create_namespaced_secret.call_args_list
        }
        assert len(created) == 2
        # The row stays, marked Failed, and its credential stays with it
        # until the row is deleted.
        core_v1.delete_namespaced_secret.assert_not_called()
        controller.uninstall.assert_awaited_once()

        after = {
            i["id"]: i
            for i in client_.get("/v1alpha1/inferenceInstance").json()
        }
        (new_id,) = set(after) - before
        assert after[new_id]["status"] == "Failed"
        assert "boom" in after[new_id]["last_error"]
        deleted = client_.delete(f"/v1alpha1/inferenceInstance/{new_id}")
        assert deleted.status_code == 200, deleted.text
        deleted_names = {
            c.kwargs["name"]
            for c in core_v1.delete_namespaced_secret.call_args_list
        }
        assert deleted_names == created


@pytest.mark.asyncio
async def test_create_inference_instance_credential_enables_the_apikey_policy(
    monkeypatch,
):
    """The store-before-install ordering is what lets protect_sdk_route
    (run from controller.install) see the credential
    Secret and create the SecurityPolicy on the very first install, using
    a real VLLMController instead of a mocked one."""
    monkeypatch.setenv("HF_API_TOKEN", "hf-test-token")
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    app = create_app()
    client_ = TestClient(app)
    model = _seeded(client_, "models", lambda m: m["category"] == "llm")
    engine = _seeded(client_, "engines", lambda e: e["name"] == "vLLM")

    api_instance, core_v1 = _gateway_mocks()
    # utils/credentials.py writes Secrets through this same CoreV1 client,
    # so protect_sdk_route's own read_namespaced_secret sees them too.
    core_v1.read_namespaced_secret.side_effect = None
    core_v1.read_namespaced_secret.return_value = mock.Mock()

    helm = mock.Mock()
    helm._command.install_or_upgrade = mock.AsyncMock()
    controller = VLLMController(
        namespace="ai-stack",
        api_instance=api_instance,
        core_v1_api=core_v1,
        helm_client=helm,
    )
    controller._add_and_update_helm_repo = mock.AsyncMock(
        return_value=mock.Mock(
            ref="vllm", repo="https://x", metadata=mock.Mock(version="1")
        )
    )

    with (
        mock.patch(
            "api.inference_instance.get_controller",
            return_value=controller,
        ),
        mock.patch(
            "utils.credentials.get_core_v1_client", return_value=core_v1
        ),
    ):
        response = client_.post(
            "/v1alpha1/inferenceInstance",
            json={"model": model, "engine": engine},
        )
        assert response.status_code == 201, response.text
        instance_id = response.json()["id"]
        release = f"vllm-{instance_id[:8]}"

        (policy,) = _created(api_instance, "SecurityPolicy")
        assert policy["metadata"]["name"] == release
        assert _target_names(policy) == [release]
        id8 = uuid.UUID(instance_id).hex[-8:]
        assert policy["spec"]["apiKeyAuth"]["credentialRefs"] == [
            {"kind": "Secret", "name": f"inf-{id8}-apikey-auth"}
        ]

        helm._command.uninstall = mock.AsyncMock()
        deleted = client_.delete(f"/v1alpha1/inferenceInstance/{instance_id}")
        assert deleted.status_code == 200, deleted.text


def test_local_chart_path_requires_the_env_and_a_chart_yaml(
    monkeypatch, tmp_path
):
    from controller.base_controller import local_chart_path

    monkeypatch.delenv("AIOPS_CHARTS_DIR", raising=False)
    assert local_chart_path("ollama") is None

    monkeypatch.setenv("AIOPS_CHARTS_DIR", str(tmp_path))
    assert local_chart_path("ollama") is None

    (tmp_path / "ollama").mkdir()
    (tmp_path / "ollama" / "Chart.yaml").write_text("name: ollama\n")
    assert local_chart_path("ollama") == tmp_path / "ollama"


@pytest.mark.asyncio
async def test_controller_prefers_the_local_chart(monkeypatch, tmp_path):
    (tmp_path / "ollama").mkdir()
    (tmp_path / "ollama" / "Chart.yaml").write_text("name: ollama\n")
    monkeypatch.setenv("AIOPS_CHARTS_DIR", str(tmp_path))
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    seen = {}

    async def fake_get_chart(helm, chart_name, *, repo=None, version=None):
        seen.update(chart_name=chart_name, repo=repo)
        return "chart"

    monkeypatch.setattr("controller.base_controller.get_chart", fake_get_chart)
    engine_chart = EngineChartsSchema(
        id=genid.uuid4(),
        engine="ollama",
        chart_type="llm",
        chart_repo="https://infracloudio.github.io/charts",
        chart_name="ollama",
    )
    instance = mock.Mock()
    assert (
        await controller._add_and_update_helm_repo(instance, engine_chart)
        == "chart"
    )
    assert seen == {"chart_name": str(tmp_path / "ollama"), "repo": None}


@pytest.mark.asyncio
async def test_ollama_controller_helm_values(snapshot):
    controller = get_controller("ollama", core_v1_api=mock.Mock())
    engine = EngineSchema(
        id=genid.uuid4(), name="Ollama", llm_support=True, cpu=True
    )
    model = ModelSchema(
        id=genid.uuid4(),
        name="Qwen3 0.6B",
        modelId="qwen3:0.6b",
        category="llm",
    )
    instance = InferenceInstanceSchema(
        id=genid.uuid4(),
        model=model,
        engine=engine,
        host=None,
        config=InferenceInstanceConfigParamsSchema(
            id=genid.uuid4(), env_vars={"OLLAMA_NUM_PARALLEL": "1"}
        ),
    )
    engine_chart = EngineChartsSchema(
        id=genid.uuid4(),
        engine="ollama",
        chart_type="llm",
        chart_repo="https://infracloudio.github.io/charts",
        chart_name="ollama",
    )
    values = await controller.prepare_helm_values(instance, engine_chart)
    assert values["models"]["pull"] == ["qwen3:0.6b"]
    assert values["service"] == {"type": "ClusterIP", "port": 80}
    assert "nvidia.com/gpu" not in yaml.dump(values)
    assert {"name": "OLLAMA_NUM_PARALLEL", "value": "1"} in values["env"]
    # The chart's fullname helper collapses to the release name because
    # the release "ollama-<id>" contains the chart name.
    release = controller._get_release_name(instance)
    assert controller.get_service_name(instance, engine_chart) == release
    snapshot.assert_match(yaml.dump(values), "ollama-values.yaml")


@pytest.mark.asyncio
async def test_ollama_controller_helm_values_uses_the_serving_option_reference():
    """Phase 3: a GGUF serving option's reference (a hf.co/<repo>:<quant>
    pull) is what gets pulled, not the catalog row's modelId."""
    controller = get_controller("ollama", core_v1_api=mock.Mock())
    engine = EngineSchema(
        id=genid.uuid4(), name="Ollama", llm_support=True, cpu=True
    )
    model = ModelSchema(
        id=genid.uuid4(),
        name="Qwen3 0.6B GGUF",
        modelId="Qwen/Qwen3-0.6B-GGUF",
        category="llm",
    )
    instance = InferenceInstanceSchema(
        id=genid.uuid4(),
        model=model,
        engine=engine,
        host=None,
        reference="hf.co/Qwen/Qwen3-0.6B-GGUF:Q8_0",
        config=InferenceInstanceConfigParamsSchema(id=genid.uuid4()),
    )
    engine_chart = EngineChartsSchema(
        id=genid.uuid4(),
        engine="ollama",
        chart_type="llm",
        chart_repo="https://infracloudio.github.io/charts",
        chart_name="ollama",
    )
    values = await controller.prepare_helm_values(instance, engine_chart)
    assert values["models"]["pull"] == ["hf.co/Qwen/Qwen3-0.6B-GGUF:Q8_0"]


@pytest.mark.asyncio
async def test_gpu_count_helm_values(snapshot):
    """Spec 6.3: gpu_count 1, 2 and 4 for vLLM and TGI, verified by
    rendered values only (lab check pending)."""
    charts = {
        "vllm": EngineChartsSchema(
            id=genid.uuid4(),
            engine="vllm",
            chart_type="llm",
            chart_repo="https://infracloudio.github.io/charts",
            chart_name="vllm",
        ),
        "huggingface": EngineChartsSchema(
            id=genid.uuid4(),
            engine="huggingface",
            chart_type="llm",
            chart_repo="https://infracloudio.github.io/charts",
            chart_name="text-generation-inference",
        ),
    }
    model = ModelSchema(
        id=genid.uuid4(),
        name="test-model",
        modelId="org/model",
        category="llm",
        size=1,
    )
    for engine_name, chart in charts.items():
        controller = get_controller(engine_name, core_v1_api=mock.Mock())
        for gpu_count in (1, 2, 4):
            instance = InferenceInstanceSchema(
                id=genid.uuid4(),
                model=model,
                engine=EngineSchema(id=genid.uuid4(), name=engine_name),
                gpu_count=gpu_count,
                replicas=2,
                cpu="8",
                memory="32Gi",
                config=InferenceInstanceConfigParamsSchema(id=genid.uuid4()),
            )
            values = await controller.prepare_helm_values(instance, chart)
            assert values["replicaCount"] == 2
            assert values["resources"]["limits"]["nvidia.com/gpu"] == gpu_count
            assert values["resources"]["requests"] == {
                "nvidia.com/gpu": gpu_count,
                "cpu": "8",
                "memory": "32Gi",
            }
            if engine_name == "vllm":
                args = values["args"] or []
                assert ("--tensor-parallel-size" in args) == (gpu_count > 1)
                if gpu_count > 1:
                    index = args.index("--tensor-parallel-size")
                    assert args[index + 1] == str(gpu_count)
            else:
                env = {e["name"]: e.get("value") for e in values["env"]}
                assert ("NUM_SHARD" in env) == (gpu_count > 1)
                if gpu_count > 1:
                    assert env["NUM_SHARD"] == str(gpu_count)
            snapshot.assert_match(
                yaml.dump(values), f"{engine_name}-gpu-{gpu_count}.yaml"
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["embedding", "reranker"])
async def test_nim_templates_keep_their_defaults_without_cpu_and_memory(
    category,
):
    """The NIM embedding and reranker templates carry their own cpu and
    memory defaults through Jinja's default(), which only fills undefined
    values: an unset cpu/memory must not reach the context as None."""
    controller = get_controller("nim", core_v1_api=mock.Mock())
    model = ModelSchema(
        id=genid.uuid4(),
        name="nv-embed",
        modelId="nvidia/x",
        category=category,
    )
    chart = EngineChartsSchema(
        id=genid.uuid4(),
        engine="nim",
        chart_type=category,
        chart_repo="https://helm.ngc.nvidia.com/nim/charts/",
        chart_name=f"nim-{category}-1.0.0.tgz",
    )
    unset = InferenceInstanceSchema(
        id=genid.uuid4(),
        model=model,
        engine=EngineSchema(id=genid.uuid4(), name="nim"),
        gpu_count=2,
        config=InferenceInstanceConfigParamsSchema(id=genid.uuid4()),
    )
    context = controller._get_base_context(unset)
    assert set(context["resources"]["requests"]) == {"gpu"}
    values = await controller.prepare_helm_values(unset, chart)
    assert values["resources"]["requests"]["memory"] == "16Gi"
    assert values["resources"]["requests"]["cpu"] == "4000m"
    assert values["resources"]["limits"]["memory"] == "32Gi"
    assert values["resources"]["limits"]["nvidia.com/gpu"] == 2
    assert "None" not in yaml.dump(values)

    given = unset.model_copy(update={"cpu": "8000m", "memory": "64Gi"})
    values = await controller.prepare_helm_values(given, chart)
    assert values["resources"]["requests"]["memory"] == "64Gi"
    assert values["resources"]["limits"]["cpu"] == "8000m"


def test_vllm_keeps_a_user_supplied_tensor_parallel_size():
    controller = get_controller("vllm", core_v1_api=mock.Mock())
    instance, chart = _inference_instance_and_chart()
    instance.gpu_count = 4
    instance.config.args = {"--tensor-parallel-size": "2"}
    context = controller._get_engine_specific_context(instance, chart)
    names = [a["name"] for a in context["args"]]
    assert names.count("--tensor-parallel-size") == 1
    assert (
        context["args"][names.index("--tensor-parallel-size")]["value"] == "2"
    )


@pytest.mark.asyncio
async def test_ollama_renders_cpu_and_memory_from_the_row():
    controller = get_controller("ollama", core_v1_api=mock.Mock())
    engine = EngineSchema(id=genid.uuid4(), name="Ollama", cpu=True)
    model = ModelSchema(
        id=genid.uuid4(), name="q", modelId="qwen3:0.6b", category="llm"
    )
    chart = EngineChartsSchema(
        id=genid.uuid4(),
        engine="ollama",
        chart_type="llm",
        chart_repo="https://infracloudio.github.io/charts",
        chart_name="ollama",
    )
    instance = InferenceInstanceSchema(
        id=genid.uuid4(),
        model=model,
        engine=engine,
        gpu_count=4,
        replicas=1,
        cpu="2",
        memory="6Gi",
        config=InferenceInstanceConfigParamsSchema(id=genid.uuid4()),
    )
    values = await controller.prepare_helm_values(instance, chart)
    assert values["replicaCount"] == 1
    assert values["resources"] == {
        "requests": {"cpu": "2", "memory": "6Gi"},
        "limits": {"cpu": "2", "memory": "6Gi"},
    }
    assert "nvidia.com/gpu" not in yaml.dump(values)


def test_merge_values_is_recursive_and_does_not_mutate():
    from controller.base_controller import merge_values

    base = {"replicaCount": 1, "resources": {"limits": {"cpu": "1"}}}
    merged = merge_values(
        base, {"replicaCount": 0, "resources": {"limits": {"memory": "1Gi"}}}
    )
    assert merged == {
        "replicaCount": 0,
        "resources": {"limits": {"cpu": "1", "memory": "1Gi"}},
    }
    assert base == {"replicaCount": 1, "resources": {"limits": {"cpu": "1"}}}
    assert merge_values(base, None) is base


@pytest.mark.asyncio
async def test_upgrade_merges_overrides_into_the_values():
    instance, chart = _inference_instance_and_chart()
    helm = mock.Mock()
    helm._command.install_or_upgrade = mock.AsyncMock()
    controller = VLLMController(
        namespace="ai-stack", core_v1_api=mock.Mock(), helm_client=helm
    )
    controller._add_and_update_helm_repo = mock.AsyncMock(
        return_value=mock.Mock(
            ref="vllm", repo=chart.chart_repo, metadata=mock.Mock(version="1")
        )
    )
    await controller.upgrade(instance, chart, overrides={"replicaCount": 0})
    values = helm._command.install_or_upgrade.await_args.args[2]
    assert values["replicaCount"] == 0
    # The rest of the rendered values is untouched by the override.
    assert values["service"] == {"type": "ClusterIP", "port": 80}
    assert values["resources"]["limits"]["nvidia.com/gpu"] == 1


@pytest.mark.asyncio
async def test_constructing_a_controller_builds_no_client(monkeypatch):
    """Construction is cheap: neither the kube config nor `helm version`
    (the Helm client's constructor) runs until the first install or
    upgrade, so request handlers and the pollers can build one per call."""
    monkeypatch.delenv("AIOPS_PARENT_DOMAIN", raising=False)
    helm = mock.Mock()
    helm._command.install_or_upgrade = mock.AsyncMock()
    helm_factory = mock.Mock(return_value=helm)
    core_factory = mock.Mock(return_value=mock.Mock())
    monkeypatch.setattr("controller.base_controller.HelmClient", helm_factory)
    monkeypatch.setattr(
        "controller.base_controller.get_core_v1_client", core_factory
    )
    instance, chart = _inference_instance_and_chart()

    controller = get_controller("vllm")
    assert controller.namespace == "ai-stack"
    await controller.prepare_helm_values(instance, chart)
    helm_factory.assert_not_called()
    core_factory.assert_not_called()

    controller._add_and_update_helm_repo = mock.AsyncMock(
        return_value=mock.Mock(
            ref="vllm", repo=chart.chart_repo, metadata=mock.Mock(version="1")
        )
    )
    await controller.upgrade(instance, chart, overrides={"replicaCount": 2})
    helm_factory.assert_called_once_with()
    helm._command.install_or_upgrade.assert_awaited_once()
    # Built once, then reused.
    assert controller.helm is controller.helm
    await controller.upgrade(instance, chart)
    helm_factory.assert_called_once_with()


@pytest.mark.asyncio
async def test_ensure_helm_builds_the_client_off_the_event_loop(monkeypatch):
    """should-fix 1 (PR 25 review): pyhelm3.Client.__init__ ends in a
    blocking `helm version` subprocess. stop/resume/scale used to build
    the whole controller -- Helm client included -- inside
    asyncio.to_thread; _ensure_helm must keep that seam even though
    construction is now lazy, so the first build never runs inline on
    the request loop."""
    main_thread = threading.current_thread()
    built_off_loop = threading.Event()

    def fake_helm_client():
        if threading.current_thread() is main_thread:
            raise AssertionError("HelmClient() ran on the event loop thread")
        built_off_loop.set()
        return mock.Mock()

    monkeypatch.setattr(
        "controller.base_controller.HelmClient", fake_helm_client
    )
    controller = get_controller("vllm", core_v1_api=mock.Mock())

    helm = await controller._ensure_helm()

    assert built_off_loop.is_set()
    assert controller.helm is helm
    # Cached: a second call does not build another one.
    assert await controller._ensure_helm() is helm


@pytest.mark.asyncio
async def test_vectordb_controller_install_fails_when_the_apikey_policy_fails(
    monkeypatch,
):
    """The API-key policy is strict: when it cannot be created the "-api"
    route is deleted again, so the database is never served with nothing
    checking the key."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    helm = _helm_with_chart(MILVUS_CHART_METADATA)
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(
        shared_targets=["sso"], secret_exists=True
    )
    create = api_instance.create_namespaced_custom_object.side_effect

    def fail_apikey_policy(group, version, namespace, plural, body, **kwargs):
        if plural == "securitypolicies" and "apiKeyAuth" in body.get(
            "spec", {}
        ):
            raise ApiException(status=500)
        if create is not None:
            return create(group, version, namespace, plural, body, **kwargs)
        return body

    api_instance.create_namespaced_custom_object.side_effect = (
        fail_apikey_policy
    )
    controller = VectorDBController(
        namespace="ai-stack",
        core_v1_api=core,
        api_instance=api_instance,
        helm_client=helm,
    )
    instance = _milvus_instance()
    release = controller._get_release_name(instance)

    with pytest.raises(ApiKeyPolicyError):
        await controller.install(instance, credential="s3cret")

    deleted = [
        (c.args[3], c.args[4])
        for c in api_instance.delete_namespaced_custom_object.call_args_list
    ]
    assert ("httproutes", f"{release}-api") in deleted


@pytest.mark.asyncio
async def test_inference_controller_install_fails_when_the_route_fails(
    monkeypatch,
):
    """The inf- route create is strict too: without it there is nothing
    to attach a policy to, and the failure keeps its own type."""
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    instance, chart = _inference_instance_and_chart()
    helm = mock.Mock()
    helm._command.install_or_upgrade = mock.AsyncMock()
    api_instance, core = _gateway_mocks(secret_exists=True)
    api_instance.create_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    controller = get_controller(
        "vllm",
        namespace="ai-stack",
        api_instance=api_instance,
        core_v1_api=core,
        helm_client=helm,
    )
    controller._add_and_update_helm_repo = mock.AsyncMock(
        return_value=mock.Mock(
            ref="vllm", repo=chart.chart_repo, metadata=mock.Mock(version="1")
        )
    )

    with pytest.raises(ApiKeyPolicyError) as excinfo:
        await controller.install(instance, chart)

    assert not isinstance(excinfo.value, HelmInstallError)
