import yaml
from jinja2 import Environment, FileSystemLoader
from kubernetes import client
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError

from api.kubernetes_utils import get_kubernetes_client
from controller.base_controller import HelmInstallError, HelmUninstallError, HelmUpgradeError
from logger import setup_logger
from schemas.vectordb_instance import VectorDBInstanceSchema


class VectorDBController():

    def __init__(self, namespace="ai-stack"):
        self.logger = setup_logger(__name__)
        self.api_instance = client.CustomObjectsApi()
        self.core_v1_api = get_kubernetes_client()
        self.namespace = namespace
        self.helm = HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader("templates"))

    def _get_release_name(self, instance: VectorDBInstanceSchema):
        return f"{instance.vectorDB.chart_name.lower()}-{str(instance.id)[:8]}"

    def get_service_name(self, instance: VectorDBInstanceSchema):
        return f"{self._get_release_name(instance)}"

    def get_pod_labels(self, instance: VectorDBInstanceSchema):
        return (f"app.kubernetes.io/instance={self._get_release_name(instance)},"
                f"app.kubernetes.io/name={instance.vectorDB.chart_name}")

    async def _prepare_helm_values(self, instance: VectorDBInstanceSchema):
        template = self.jinja_env.get_template(
            f"{instance.vectorDB.chart_name.lower()}-values.yaml.jinja"
        )

        context = self._get_base_context(instance)

        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        return values

    def _get_base_context(self, instance: VectorDBInstanceSchema):
        service_type = "LoadBalancer" # default service type
        if instance.configParams and instance.configParams["serviceType"]:
            service_type = instance.configParams["serviceType"]

        return {
            "service_type": service_type
        }

    async def _add_and_update_helm_repo(self, instance: VectorDBInstanceSchema):
        repo_url = instance.vectorDB.chart_repo
        chart_name = instance.vectorDB.chart_name

        chart = await self.helm.get_chart(chart_name, repo=repo_url)
        self.logger.info(f"fetched chart: {chart_name} from {repo_url}")

        return chart

    async def install(self, instance: VectorDBInstanceSchema):
        self.logger.debug(f"Installing instance: {instance}")
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self._prepare_helm_values(instance)

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

    async def upgrade(self, instance: VectorDBInstanceSchema):
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self._prepare_helm_values(instance)

        try:
            await self.helm.install_or_upgrade_release(
                chart_name, chart, values, namespace=self.namespace)
            self.logger.info(f"Helm upgrade succeeded for chart: {chart_name}")
        except Exception as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm upgrade failed: {str(e)}")
            raise HelmUpgradeError(
                f"Helm upgrade failed: {str(e)}") from e

    async def uninstall(self, instance: VectorDBInstanceSchema):
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
                f"Helm uninstall failed: {str(e)}") from e
