from abc import ABC, abstractmethod

import yaml
from jinja2 import Environment, FileSystemLoader
from kubernetes import client
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError

from api.kubernetes_utils import load_kubernetes_config
from logger import setup_logger
from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema


class Controller(ABC):

    def __init__(self, namespace="ai-stack"):
        config_source = load_kubernetes_config()
        self.logger = setup_logger(__name__)
        self.logger.debug(
            f"Loaded Kubernetes configuration from: {config_source}")
        self.api_instance = client.CustomObjectsApi()
        self.core_v1_api = client.CoreV1Api()
        self.namespace = namespace
        self.helm = HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader("templates"))

    def _get_release_name(self, instance: InferenceInstanceSchema):
        # name = <engine_name>-<instance_id_first_8_chars>
        return f"{instance.engine.name.lower()}-{str(instance.id)[:8]}"

    def get_service_name(self, instance: InferenceInstanceSchema,
                         engineChart: EngineChartsSchema):
        return f"{self._get_release_name(instance)}-{engineChart.chart_name}"

    def get_pod_labels(self, instance: InferenceInstanceSchema,
                       engineChart: EngineChartsSchema):
        return f"app.kubernetes.io/instance={self._get_release_name(instance)},app.kubernetes.io/name={engineChart.chart_name}"

    async def _prepare_helm_values(self, instance: InferenceInstanceSchema,
                                   engineChart: EngineChartsSchema):
        template = self.jinja_env.get_template(
            f"{instance.engine.name.lower()}-{instance.model.category}-values.yaml.jinja"
        )

        context = self._get_base_context(instance)
        self.logger.info(f"Base context: {context}")
        self.logger.info(
            f"Engine specific context: {self._get_engine_specific_context(instance, engineChart)}"
        )
        context.update(self._get_engine_specific_context(
            instance, engineChart))

        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        self.logger.info(f"{instance.engine.name} values: {values}")
        return values

    def _get_base_context(self, instance: InferenceInstanceSchema):
        return {
            "nodeSelector": {
                "hostname": instance.host
            },
            "service": {
                "type": "LoadBalancer",
                "port": 80
            },
            "resources": {
                "limits": {
                    "gpu": 1
                },
                "requests": {
                    "gpu": 1
                }
            },
            "volumes": {
                "hf_cache": {
                    "claimName": "hf-cache"
                }
            },
            "volumeMounts": {
                "hf_cache": {
                    "mountPath": "/data"
                }
            },
        }

    @abstractmethod
    def _get_engine_specific_context(self, instance: InferenceInstanceSchema,
                                     engineChart: EngineChartsSchema):
        pass

    async def _add_and_update_helm_repo(self,
                                        instance: InferenceInstanceSchema,
                                        engineChart: EngineChartsSchema):
        repo_url = engineChart.chart_repo
        chart_name = engineChart.chart_name

        chart = await self.helm.get_chart(chart_name, repo=repo_url)
        self.logger.info(f"fetched chart: {chart_name} from {repo_url}")

        return chart

    async def install(self, instance: InferenceInstanceSchema,
                      engineChart: EngineChartsSchema):
        self.logger.debug(f"Installing instance: {instance}")
        chart = await self._add_and_update_helm_repo(instance, engineChart)
        chart_name = self._get_release_name(instance)
        values = await self._prepare_helm_values(instance, engineChart)

        try:
            await self.helm.install_or_upgrade_release(
                chart_name,
                chart,
                values,
                namespace=self.namespace,
                create_namespace=True,
            )
            self.logger.info(f"Helm install succeeded for chart: {chart_name}")
        except Exception as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm install failed: {str(e)}")
            raise HelmInstallError(
                f"Helm install failed: {str(e)}") from e  # {{ edit_1 }}

    def _unlink_downloaded_chart(self, instance: InferenceInstanceSchema):
        return

    async def upgrade(self, instance: InferenceInstanceSchema,
                      engineChart: EngineChartsSchema):
        chart = await self._add_and_update_helm_repo(instance, engineChart)
        chart_name = self._get_release_name(instance)
        values = await self._prepare_helm_values(instance, engineChart)

        try:
            await self.helm.install_or_upgrade_release(
                chart_name, chart, values, namespace=self.namespace)
            self.logger.info(f"Helm upgrade succeeded for chart: {chart_name}")
        except Exception as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm upgrade failed: {str(e)}")
            raise HelmUpgradeError(
                f"Helm upgrade failed: {str(e)}") from e  # {{ edit_2 }}

    async def uninstall(self, instance: InferenceInstanceSchema,
                        engineChart: EngineChartsSchema):
        chart_name = self._get_release_name(instance)

        try:
            revision = await self.helm.get_current_revision(
                chart_name, namespace=self.namespace)
            self.logger.info(f"Current revision: {revision}")
            await revision.release.uninstall(wait=True)
            self.logger.info(
                f"Helm uninstall succeeded for chart: {chart_name}")
        except ReleaseNotFoundError:
            self.logger.error(f"Release not found: {chart_name}")
        except Exception as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm uninstall failed: {str(e)}")
            raise HelmUninstallError(
                f"Helm uninstall failed: {str(e)}") from e  # {{ edit_3 }}
        finally:
            self._unlink_downloaded_chart(instance)


class HelmInstallError(Exception):
    pass


class HelmUpgradeError(Exception):
    pass


class HelmUninstallError(Exception):
    pass
