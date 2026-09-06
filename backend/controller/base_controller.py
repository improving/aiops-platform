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
from utils.gateway import (
    INFERENCE_TIMEOUTS,
    apikey_secret_name,
    delete_backend_traffic_policy,
    delete_http_route,
    delete_security_policy,
    ensure_apikey_policy,
    ensure_backend_traffic_policy,
    ensure_http_route,
    instance_hostname,
)
from utils.kubernetes_utils import get_core_v1_client, get_default_namespace

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


class Controller(ABC):
    def __init__(
        self,
        namespace: str | None = None,
        api_instance: client.CustomObjectsApi = None,
        core_v1_api: client.CoreV1Api = None,
        helm_client: HelmClient = None,
    ):
        self.logger = setup_logger(__name__)
        # core_v1_api first: get_core_v1_client() loads the kube config,
        # which client.CustomObjectsApi() below silently needs too (it
        # reads the kubernetes client's global default Configuration).
        self.core_v1_api = core_v1_api or get_core_v1_client()
        self.api_instance = api_instance or client.CustomObjectsApi()
        self.namespace = namespace or get_default_namespace()
        self.helm = helm_client or HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

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

        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        self.logger.info(f"{instance.engine.name} values: {values}")
        return values

    def _get_base_context(self, instance: InferenceInstanceSchema):
        base_context = {
            "nodeSelector": {},
            "service": {"type": "ClusterIP", "port": 80},
            "resources": {"limits": {"gpu": 1}, "requests": {"gpu": 1}},
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
        browser UI) and, once its credential Secret exists (Task 12), the
        API-key policy on it. No-op without the gateway env contract."""
        route_name = self._gateway_route_name(instance)
        self._safe_gateway_call(
            f"Failed to ensure gateway route {route_name} for {instance.id}",
            ensure_http_route,
            self.namespace,
            route_name,
            instance_hostname("inf", instance.id),
            self.get_service_name(instance, engineChart),
            INFERENCE_GATEWAY_PORT,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to ensure the API-key policy for {route_name}",
            ensure_apikey_policy,
            self.namespace,
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
        """Policy first, then the route it targets. Called from a
        `finally`, where a new exception would silently replace the one
        already being propagated; see _safe_gateway_call."""
        route_name = self._gateway_route_name(instance)
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
        self._safe_gateway_call(
            f"Failed to delete gateway route {route_name} for {instance.id}",
            delete_http_route,
            self.namespace,
            route_name,
            api_instance=self.api_instance,
        )

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
            self._ensure_gateway_routes(instance, engineChart)
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
    ):
        chart = await self._add_and_update_helm_repo(instance, engineChart)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance, engineChart)

        try:
            await install_or_upgrade_release(
                self.helm, chart_name, chart, values, namespace=self.namespace
            )
            self.logger.info(f"Helm upgrade succeeded for chart: {chart_name}")
            self._ensure_gateway_routes(instance, engineChart)
        except (
            Exception
        ) as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm upgrade failed: {str(e)}")
            raise HelmUpgradeError(
                f"Helm upgrade failed: {str(e)}"
            ) from e  # {{ edit_2 }}

    async def uninstall(self, instance: InferenceInstanceSchema):
        chart_name = self._get_release_name(instance)

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
            self._delete_gateway_routes(instance)
            self._unlink_downloaded_chart(instance)


class HelmInstallError(Exception):
    pass


class HelmUpgradeError(Exception):
    pass


class HelmUninstallError(Exception):
    pass
