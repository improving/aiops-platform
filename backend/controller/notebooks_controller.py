import yaml
from jinja2 import Environment, FileSystemLoader
from kubernetes import client
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError

from logger import setup_logger
from paths import TEMPLATES_DIR
from schemas.notebook import NotebookInstanceSchema
from utils.kubernetes_utils import get_core_v1_client

from .base_controller import (
    HelmInstallError,
    HelmUninstallError,
    HelmUpgradeError,
)


class NotebooksController:
    def __init__(
        self,
        api_instance: client.CustomObjectsApi = None,
        core_v1_api: client.CoreV1Api = None,
        helm: HelmClient = None,
    ):
        self.logger = setup_logger(__name__)
        self.api_instance = api_instance or client.CustomObjectsApi()
        self.core_v1_api = core_v1_api or get_core_v1_client()
        self.helm = helm or HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

    def _get_release_name(self, instance: NotebookInstanceSchema):
        return f"{instance.name.lower()}-{str(instance.id)[:8]}"

    def get_service_name(self, instance: NotebookInstanceSchema):
        return (
            f"{self._get_release_name(instance)}-kf-notebooks-{instance.name}"[
                :41
            ].rstrip("-")
        )

    def get_pod_labels(self, instance: NotebookInstanceSchema):
        return (
            f"app.kubernetes.io/instance={self._get_release_name(instance)},"
            f"app.kubernetes.io/name=kf-notebooks"
        )

    async def prepare_helm_values(self, instance: NotebookInstanceSchema):
        template = self.jinja_env.get_template(
            "kf-notebooks-values.yaml.jinja"
        )
        context = self._get_base_context(instance)
        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        return values

    def _get_instance_image(
        self, notebook_type: str, framework: str, nvidia_gpu: bool
    ):
        if notebook_type.lower() == "jupyter":
            if nvidia_gpu:
                image_suffix = "-cuda-full"
            else:
                image_suffix = "-full"
            image = f"kubeflownotebookswg/jupyter-{framework.lower()}{image_suffix}"
        elif notebook_type.lower() == "vscode":
            if framework and framework.lower() == "python":
                image_suffix = "-python"
            else:
                image_suffix = ""
            image = f"kubeflownotebookswg/codeserver{image_suffix}"
        else:
            raise ValueError(f"Invalid notebook type: {notebook_type}")

        return image

    def _get_base_context(self, instance: NotebookInstanceSchema):
        image_tag = ""
        if not instance.image or instance.image == "":
            instance.image = self._get_instance_image(
                instance.type, instance.framework, instance.nvidia_gpu
            )
        else:
            instance.image, image_tag = instance.image.split(":")

        context = {
            "service": {
                "type": instance.service_type,
                "port": instance.service_port,
            },
            "image": {
                "repository": instance.image,
                "tag": image_tag,
            },
            "name": instance.name,
            "resources": {
                "limits": {
                    "cpu": instance.resources_cpu,
                    "memory": instance.resources_memory,
                    "nvidia.com/gpu": instance.resources_gpu,
                },
                "requests": {
                    "cpu": instance.resources_cpu,
                    "memory": instance.resources_memory,
                    "nvidia.com/gpu": instance.resources_gpu,
                },
            },
            "storage": {
                "size": instance.storage_size,
            },
            "nvidia_gpu": instance.nvidia_gpu,
        }

        # Filter out empty or None values
        context = {k: v for k, v in context.items() if v not in [None, ""]}
        context["service"] = {
            k: v for k, v in context["service"].items() if v not in [None, ""]
        }
        context["resources"]["limits"] = {
            k: v
            for k, v in context["resources"]["limits"].items()
            if v not in [None, ""]
        }
        context["resources"]["requests"] = {
            k: v
            for k, v in context["resources"]["requests"].items()
            if v not in [None, ""]
        }
        context["storage"] = {
            k: v for k, v in context["storage"].items() if v not in [None, ""]
        }

        if instance.type == "jupyter":
            type_specific_context = {
                "notebooks": {
                    "jupyter": {"enabled": True},
                    "vscode": {"enabled": False},
                }
            }
            context.update(type_specific_context)
        elif instance.type == "vscode":
            type_specific_context = {
                "notebooks": {
                    "vscode": {"enabled": True},
                    "jupyter": {"enabled": False},
                }
            }
            context.update(type_specific_context)

        return context

    async def _add_and_update_helm_repo(
        self, instance: NotebookInstanceSchema
    ):
        repo_url = "https://infracloudio.github.io/charts"
        chart_name = "kf-notebooks"

        chart = await self.helm.get_chart(chart_name, repo=repo_url)
        self.logger.info(f"fetched chart: {chart_name} from {repo_url}")

        return chart

    async def install(self, instance: NotebookInstanceSchema):
        self.logger.debug(f"Installing instance: {instance}")
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance)

        try:
            await self.helm.install_or_upgrade_release(
                chart_name,
                chart,
                values,
                namespace=instance.namespace,
                create_namespace=True,
            )
            self.logger.info(f"Helm install succeeded for chart: {chart_name}")
        except Exception as e:
            self.logger.exception(f"Helm install failed: {str(e)}")
            raise HelmInstallError(f"Helm install failed: {str(e)}") from e

    async def upgrade(self, instance: NotebookInstanceSchema):
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance)

        try:
            await self.helm.install_or_upgrade_release(
                chart_name, chart, values, namespace=instance.namespace
            )
            self.logger.info(f"Helm upgrade succeeded for chart: {chart_name}")
        except Exception as e:
            self.logger.exception(f"Helm upgrade failed: {str(e)}")
            raise HelmUpgradeError(f"Helm upgrade failed: {str(e)}") from e

    async def uninstall(self, instance: NotebookInstanceSchema):
        chart_name = self._get_release_name(instance)

        try:
            revision = await self.helm.get_current_revision(
                chart_name, namespace=instance.namespace
            )
            self.logger.info(f"Current revision: {revision}")
            await revision.release.uninstall(wait=True)
            self.logger.info(
                f"Helm uninstall succeeded for chart: {chart_name}"
            )
        except ReleaseNotFoundError:
            self.logger.error(f"Release not found: {chart_name}")
        except Exception as e:
            self.logger.exception(f"Helm uninstall failed: {str(e)}")
            raise HelmUninstallError(f"Helm uninstall failed: {str(e)}") from e
