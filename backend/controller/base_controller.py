import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from pydantic import ValidationError
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError
from pyhelm3.models import Chart

from logger import setup_logger
from paths import TEMPLATES_DIR
from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema
from utils.credentials import _apply_secret, _secret_body
from utils.gateway import (
    INFERENCE_TIMEOUTS,
    ApiKeyPolicyError,
    GatewayPolicyError,
    apikey_secret_name,
    delete_backend_traffic_policy,
    delete_http_route,
    delete_security_policy,
    ensure_backend_traffic_policy,
    ensure_http_route,
    instance_hostname,
    protect_sdk_route,
)
from utils.kubernetes_utils import get_core_v1_client, get_default_namespace
from utils.render_guard import refuse_line_breaks

HF_API_TOKEN_SECRET = "hf-api-token"

# Chart.yaml keys that Helm needs; every other key is informational.
REQUIRED_CHART_METADATA_KEYS = frozenset({"apiVersion", "name", "version"})

# Inference engines only ever expose one port through their chart's Service.
INFERENCE_GATEWAY_PORT = 80

# A directory of chart sources (the monorepo's charts/) that wins over the
# published repository, so a chart can be tried before it is released.
CHARTS_DIR_ENV = "AIOPS_CHARTS_DIR"


def local_chart_path(chart_name: str) -> Path | None:
    """``<AIOPS_CHARTS_DIR>/<chart_name>`` when the env var is set and the
    directory holds a ``Chart.yaml``; ``None`` otherwise."""
    charts_dir = os.environ.get(CHARTS_DIR_ENV)
    if not charts_dir:
        return None
    path = Path(charts_dir) / chart_name
    if (path / "Chart.yaml").is_file():
        return path
    return None


class ChartMetadataError(Exception):
    """The Chart.yaml of a chart does not pass pyhelm3 validation."""


async def get_chart(
    helm: HelmClient,
    chart_name: str,
    *,
    repo: str | None = None,
    version: str | None = None,
) -> Chart:
    """Fetch a chart like HelmClient.get_chart, but tolerate bad metadata.

    pyhelm3 validates Chart.yaml with pydantic and rejects, for example,
    the Milvus chart whose maintainers[0].url is the bare hostname
    "milvus.io". Helm itself does not care, and the install only needs
    name and version, so drop the informational keys that fail and retry.
    """
    metadata = await helm._command.show_chart(
        chart_name, devel=False, repo=repo, version=version
    )
    try:
        return Chart(
            helm._command, ref=chart_name, repo=repo, metadata=metadata
        )
    except ValidationError as e:
        bad_keys = {
            error["loc"][1]
            for error in e.errors()
            if len(error["loc"]) > 1 and error["loc"][0] == "metadata"
        }
        if not bad_keys or bad_keys & REQUIRED_CHART_METADATA_KEYS:
            raise ChartMetadataError(
                f"Chart {chart_name!r} has invalid metadata: {e}"
            ) from e
        cleaned = {k: v for k, v in metadata.items() if k not in bad_keys}
    try:
        return Chart(
            helm._command, ref=chart_name, repo=repo, metadata=cleaned
        )
    except ValidationError as e:
        raise ChartMetadataError(
            f"Chart {chart_name!r} has invalid metadata: {e}"
        ) from e


async def install_or_upgrade_release(
    helm: HelmClient,
    release_name: str,
    chart: Chart,
    values: dict,
    *,
    namespace: str,
    create_namespace: bool = True,
) -> None:
    """Run 'helm upgrade --install' for the chart.

    HelmClient.install_or_upgrade_release parses the release status that
    Helm prints, and that status embeds the same Chart.yaml metadata that
    get_chart() had to clean up. The controllers never use the parsed
    revision, so call the Helm command directly and skip the parsing.
    """
    await helm._command.install_or_upgrade(
        release_name,
        chart.ref,
        values,
        namespace=namespace,
        create_namespace=create_namespace,
        repo=chart.repo,
        version=chart.metadata.version,
    )


async def uninstall_release(
    helm: HelmClient, release_name: str, *, namespace: str
) -> None:
    """Run 'helm uninstall --wait' without reading the release status first.

    Reading the status parses the chart metadata, see
    install_or_upgrade_release. A missing release raises
    pyhelm3.errors.ReleaseNotFoundError as before.
    """
    await helm._command.uninstall(release_name, namespace=namespace, wait=True)


def merge_values(base: dict, overrides: dict | None) -> dict:
    """``overrides`` laid over ``base``, nested dicts merged recursively;
    neither input is mutated. Stop, resume and scale use it to change
    ``replicaCount`` without a second rendering path."""
    if not overrides:
        return base
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_values(merged[key], value)
        else:
            merged[key] = value
    return merged


class Controller(ABC):
    """The Helm workflow of one inference engine.

    Construction is cheap and never touches the cluster or the ``helm``
    binary: the Kubernetes clients and the Helm client are built on
    first use (``core_v1_api``, ``api_instance``, ``helm``), so the
    request handlers and the 5 s pollers can build one per call. The
    Helm client runs ``helm version`` when it is built, i.e. on the
    first chart lookup, install, upgrade or uninstall; ``install``/
    ``upgrade``/``uninstall`` build it through ``_ensure_helm``
    (``asyncio.to_thread``) before touching ``self.helm``, so that
    subprocess never runs inline on the request loop.
    ``install``/``upgrade``/``uninstall`` run their sync Kubernetes
    work off the event loop (``asyncio.to_thread``) too.
    """

    # Does the workload check the API key itself, or only the gateway?
    # Only vLLM does today (its chart reads the credential Secret into
    # VLLM_API_KEY). It decides whether a caller that bypasses the
    # gateway -- anything in-cluster, Langflow included -- still needs
    # the key, so the UI must not guess it from the engine name.
    workload_checks_api_key = False

    def settings_read(self, category: str) -> frozenset[str]:
        """Which of an instance's own settings this controller renders
        into the chart values: ``"args"``, ``"env_vars"``, both or none.
        The settings route refuses what is not read (an edit would
        restart the pods and change nothing), and the UI shows only what
        is, from the payload's ``settingsRead`` -- like the flag above, it
        must not guess it from the engine name."""
        return frozenset()

    def __init__(
        self,
        namespace: str | None = None,
        api_instance: client.CustomObjectsApi = None,
        core_v1_api: client.CoreV1Api = None,
        helm_client: HelmClient = None,
    ):
        self.logger = setup_logger(__name__)
        self._core_v1_api = core_v1_api
        self._api_instance = api_instance
        self._helm = helm_client
        self.namespace = namespace or get_default_namespace()
        self.jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

    @property
    def core_v1_api(self) -> client.CoreV1Api:
        """Built on first use; loads the kube config."""
        if self._core_v1_api is None:
            self._core_v1_api = get_core_v1_client()
        return self._core_v1_api

    @core_v1_api.setter
    def core_v1_api(self, value: client.CoreV1Api) -> None:
        self._core_v1_api = value

    def ensure_ready(self) -> None:
        """Force the lazy Kubernetes client to build now.

        Construction is cheap by design (see the class docstring), so a
        missing kubeconfig or an unreachable cluster no longer raises
        from ``get_controller()``; it only surfaces on the first real
        call. A caller that wants that old, eager failure -- to fail an
        engine once for a tick instead of once per row, or as a create
        pre-flight -- calls this first. Sync: run it through
        ``asyncio.to_thread`` from an ``async def``.
        """
        self.core_v1_api  # noqa: B018

    @property
    def api_instance(self) -> client.CustomObjectsApi:
        """Built on first use, after ``core_v1_api``: get_core_v1_client()
        loads the kube config, which client.CustomObjectsApi() silently
        needs too (it reads the kubernetes client's global default
        Configuration)."""
        if self._api_instance is None:
            self.core_v1_api  # noqa: B018 (loads the kube config)
            self._api_instance = client.CustomObjectsApi()
        return self._api_instance

    @api_instance.setter
    def api_instance(self, value: client.CustomObjectsApi) -> None:
        self._api_instance = value

    @property
    def helm(self) -> HelmClient:
        """The cached client. ``install``/``upgrade``/``uninstall`` call
        ``_ensure_helm`` first, so by the time anything reads this
        property the client already exists; the lazy build here is only
        a fallback for a caller outside that path."""
        if self._helm is None:
            self._helm = HelmClient()
        return self._helm

    @helm.setter
    def helm(self, value: HelmClient) -> None:
        self._helm = value

    async def _ensure_helm(self) -> HelmClient:
        """Build the Helm client off the event loop on first use.

        ``HelmClient.__init__`` ends in ``self._command.client_version()``,
        a blocking ``subprocess.run("helm version")``. Reading it back
        from ``self.helm`` afterwards is cheap, but the first build must
        never happen inline inside an ``async def`` on the request loop.
        """
        if self._helm is None:
            self._helm = await asyncio.to_thread(HelmClient)
        return self._helm

    def _get_release_name(self, instance: InferenceInstanceSchema):
        # name = <engine_name>-<instance_id_first_8_chars>
        return f"{instance.engine.name.lower()}-{str(instance.id)[:8]}"

    def get_service_name(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        return f"{self._get_release_name(instance)}-{engineChart.chart_name}"

    def get_pod_labels(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        return (
            f"app.kubernetes.io/instance={self._get_release_name(instance)},"
            f"app.kubernetes.io/name={engineChart.chart_name}"
        )

    def service_url(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ) -> str:
        """The in-cluster URL LiteLLM calls; it bypasses the gateway and
        its API-key policy, so the workload credential goes as bearer."""
        service = self.get_service_name(instance, engineChart)
        return (
            f"http://{service}.{self.namespace}.svc:{INFERENCE_GATEWAY_PORT}"
        )

    async def prepare_helm_values(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        template = self.jinja_env.get_template(
            f"{instance.engine.name.lower()}-{instance.model.category}-values.yaml.jinja"
        )

        context = self._get_base_context(instance)
        self.logger.info(f"Base context: {context}")
        self.logger.info(
            f"Engine specific context: {self._get_engine_specific_context(instance, engineChart)}"
        )
        context.update(
            self._get_engine_specific_context(instance, engineChart)
        )

        refuse_line_breaks(context)
        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        self.logger.info(f"{instance.engine.name} values: {values}")
        return values

    def _get_base_context(self, instance: InferenceInstanceSchema):
        """Values every engine template may read: the node pin, the
        Service, the replica count and the resources from the row
        (spec 6.3). cpu/memory are left out of the dict when the user
        left them empty: Jinja's default() only fills undefined values,
        so the NIM templates' own defaults (16Gi, 4000m, ...) still apply
        and no template ever renders "memory: None"."""
        resources = {"gpu": instance.gpu_count}
        if instance.cpu:
            resources["cpu"] = instance.cpu
        if instance.memory:
            resources["memory"] = instance.memory
        base_context = {
            "nodeSelector": {},
            "service": {"type": "ClusterIP", "port": 80},
            "replicaCount": instance.replicas,
            "resources": {
                "limits": dict(resources),
                "requests": dict(resources),
            },
            "volumes": {"hf_cache": {"claimName": "hf-cache"}},
            "volumeMounts": {"hf_cache": {"mountPath": "/data"}},
        }

        if instance.host:
            base_context["nodeSelector"] = {"hostname": instance.host}

        return base_context

    @abstractmethod
    def _get_engine_specific_context(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        pass

    async def _add_and_update_helm_repo(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        repo_url = engineChart.chart_repo
        chart_name = engineChart.chart_name

        local = local_chart_path(chart_name)
        if local is not None:
            chart = await get_chart(self.helm, str(local))
            self.logger.info(f"using local chart source: {local}")
            return chart

        chart = await get_chart(
            self.helm,
            chart_name,
            repo=repo_url,
            version=engineChart.chart_version,
        )
        self.logger.info(f"fetched chart: {chart_name} from {repo_url}")

        return chart

    def _gateway_route_name(self, instance: InferenceInstanceSchema):
        return self._get_release_name(instance)

    def _safe_gateway_call(self, description: str, fn, *args, **kwargs):
        """Run one gateway call, logging instead of raising on failure.

        Never raises: a gateway problem must not be mistaken for a Helm
        failure (which would leave the release installed but the row
        deleted, since the caller's except-and-delete does not know the
        difference), must not block the install/upgrade/uninstall it
        follows, and must not stop the next call from being attempted.
        What is left here is only the BackendTrafficPolicy (timeouts,
        whose failure exposes nothing) and the deletes. The inf-<id8>
        route and its API-key policy are no longer among them: they are
        strict since #27, see _ensure_gateway_routes above, because an
        unprotected inference host is served with nothing checking the
        key and only vLLM checks one itself.
        """
        try:
            fn(*args, **kwargs)
        except Exception:
            self.logger.exception(description)

    def _ensure_gateway_routes(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        """Create/patch the one SDK HTTPRoute (inf-<id8>; inference has no
        browser UI) and the API-key policy on it. No-op without the
        gateway env contract.

        Both steps are strict (fail closed, #27): an inf- route with no
        policy is an inference endpoint served with nothing checking the
        key, and no in-repo engine except vLLM checks one itself. A
        failure deletes the route again and raises ApiKeyPolicyError, so
        install/upgrade never mislabels it as a Helm error and the create
        endpoint marks the row Failed with the reason. The traffic policy
        below stays best effort: its failure exposes nothing.
        """
        route_name = self._gateway_route_name(instance)
        try:
            ensure_http_route(
                self.namespace,
                route_name,
                instance_hostname("inf", instance.id),
                self.get_service_name(instance, engineChart),
                INFERENCE_GATEWAY_PORT,
                api_instance=self.api_instance,
            )
        except Exception as e:
            raise ApiKeyPolicyError(
                f"HTTPRoute {self.namespace}/{route_name} could not be "
                f"created: {e}"
            ) from e
        protect_sdk_route(
            self.namespace,
            route_name,
            route_name,
            apikey_secret_name("inf", instance.id),
            api_instance=self.api_instance,
            core_v1_api=self.core_v1_api,
        )
        self._safe_gateway_call(
            f"Failed to ensure the traffic policy for {route_name}",
            ensure_backend_traffic_policy,
            self.namespace,
            route_name,
            api_instance=self.api_instance,
            timeouts=INFERENCE_TIMEOUTS,
        )

    def _delete_gateway_routes(self, instance: InferenceInstanceSchema):
        """The route first, then the policies that targeted it.

        The same order the other two controllers use, and for their
        reason: a policy that briefly targets a route that is gone is
        harmless, a route that outlives its API-key policy is not. This
        runs from a `finally`, so it also runs when the Helm uninstall
        raised and the workload is still serving; taking the policy away
        first would leave that workload published with nothing checking
        the key. A new exception here would silently replace the one
        already propagating, hence _safe_gateway_call.
        """
        route_name = self._gateway_route_name(instance)
        self._safe_gateway_call(
            f"Failed to delete gateway route {route_name} for {instance.id}",
            delete_http_route,
            self.namespace,
            route_name,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to delete the traffic policy for {route_name}",
            delete_backend_traffic_policy,
            self.namespace,
            route_name,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to delete the API-key policy for {route_name}",
            delete_security_policy,
            self.namespace,
            route_name,
            api_instance=self.api_instance,
        )

    async def _ensure_hf_api_token_secret(self) -> bool:
        """The Secret ``hf-api-token`` the Hugging Face engines' values
        reference, from the platform's ``HF_API_TOKEN``: created, or
        replaced so that a rotated token reaches the next pod. Without a
        token there is nothing to write and the answer is False; the
        engine decides whether it can start that way (a public model
        needs none)."""
        token = os.environ.get("HF_API_TOKEN")
        if not token:
            return False
        await asyncio.to_thread(
            _apply_secret,
            self.core_v1_api,
            self.namespace,
            _secret_body(
                HF_API_TOKEN_SECRET, self.namespace, {"HF_API_TOKEN": token}
            ),
        )
        return True

    def create_ns_if_needed(self):
        try:
            self.core_v1_api.read_namespace(self.namespace)
            self.logger.info(f"Namespace '{self.namespace}' already exists")
        except ApiException as e:
            if e.status == 404:
                self.logger.info(
                    f"Namespace '{self.namespace}' does not exist, creating..."
                )
                namespace_obj = client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=self.namespace)
                )
                self.core_v1_api.create_namespace(namespace_obj)
                self.logger.info(
                    f"Namespace '{self.namespace}' created successfully"
                )
            else:
                self.logger.exception(
                    f"Failed to check namespace '{self.namespace}': {str(e)}"
                )
                raise

    async def install(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        self.logger.debug(f"Installing instance: {instance}")
        await self._ensure_helm()
        chart = await self._add_and_update_helm_repo(instance, engineChart)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance, engineChart)

        try:
            await install_or_upgrade_release(
                self.helm,
                chart_name,
                chart,
                values,
                namespace=self.namespace,
                create_namespace=True,
            )
            self.logger.info(f"Helm install succeeded for chart: {chart_name}")
            await asyncio.to_thread(
                self._ensure_gateway_routes, instance, engineChart
            )
        except GatewayPolicyError:
            # Helm succeeded; the route could not be protected and was
            # removed again. Propagate as itself so the reason on the row
            # names the policy instead of claiming Helm failed.
            raise
        except (
            Exception
        ) as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm install failed: {str(e)}")
            raise HelmInstallError(
                f"Helm install failed: {str(e)}"
            ) from e  # {{ edit_1 }}

    def _unlink_downloaded_chart(self, instance: InferenceInstanceSchema):
        return

    async def upgrade(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
        overrides: dict | None = None,
    ):
        """helm upgrade with the rendered values; ``overrides`` (spec 6.3)
        are merged over them, so stop and resume reuse the install path."""
        await self._ensure_helm()
        chart = await self._add_and_update_helm_repo(instance, engineChart)
        chart_name = self._get_release_name(instance)
        values = merge_values(
            await self.prepare_helm_values(instance, engineChart), overrides
        )

        try:
            await install_or_upgrade_release(
                self.helm, chart_name, chart, values, namespace=self.namespace
            )
            self.logger.info(f"Helm upgrade succeeded for chart: {chart_name}")
            await asyncio.to_thread(
                self._ensure_gateway_routes, instance, engineChart
            )
        except GatewayPolicyError:
            # See install: the route is already gone, and the reason
            # should name the policy rather than claim Helm failed.
            raise
        except (
            Exception
        ) as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm upgrade failed: {str(e)}")
            raise HelmUpgradeError(
                f"Helm upgrade failed: {str(e)}"
            ) from e  # {{ edit_2 }}

    async def uninstall(self, instance: InferenceInstanceSchema):
        chart_name = self._get_release_name(instance)
        await self._ensure_helm()

        try:
            await uninstall_release(
                self.helm, chart_name, namespace=self.namespace
            )
            self.logger.info(
                f"Helm uninstall succeeded for chart: {chart_name}"
            )
        except ReleaseNotFoundError:
            self.logger.warning(f"Release not found: {chart_name}")
        except (
            Exception
        ) as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm uninstall failed: {str(e)}")
            raise HelmUninstallError(
                f"Helm uninstall failed: {str(e)}"
            ) from e  # {{ edit_3 }}
        finally:
            await asyncio.to_thread(self._delete_gateway_routes, instance)
            self._unlink_downloaded_chart(instance)


class HelmInstallError(Exception):
    pass


class HelmUpgradeError(Exception):
    pass


class HelmUninstallError(Exception):
    pass
