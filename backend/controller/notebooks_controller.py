import yaml
from jinja2 import Environment, FileSystemLoader
from kubernetes import client
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError

from logger import setup_logger
from paths import TEMPLATES_DIR
from schemas.notebook import NotebookInstanceSchema
from utils.gateway import (
    OidcPolicyError,
    delete_backend_traffic_policy,
    delete_http_route,
    ensure_backend_traffic_policy,
    ensure_gateway_client_secret,
    ensure_http_route,
    ensure_reference_grant,
    instance_hostname,
    protect_browser_route,
    remove_oidc_target,
)
from utils.kubernetes_utils import get_core_v1_client

from .base_controller import (
    HelmInstallError,
    HelmUninstallError,
    HelmUpgradeError,
    get_chart,
    install_or_upgrade_release,
    uninstall_release,
)


class NotebooksController:
    def __init__(
        self,
        api_instance: client.CustomObjectsApi = None,
        core_v1_api: client.CoreV1Api = None,
        helm: HelmClient = None,
    ):
        self.logger = setup_logger(__name__)
        # core_v1_api first: get_core_v1_client() loads the kube config,
        # which client.CustomObjectsApi() below silently needs too (it
        # reads the kubernetes client's global default Configuration).
        self.core_v1_api = core_v1_api or get_core_v1_client()
        self.api_instance = api_instance or client.CustomObjectsApi()
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

    def _safe_gateway_call(self, description: str, fn, *args, **kwargs):
        """Run one best-effort gateway call, logging instead of raising.

        Used for the BackendTrafficPolicy (only timeouts), the client
        Secret copy and the ReferenceGrants (dev-stack helpers for a
        second namespace), and every delete (called from a `finally`,
        where a new exception would replace the one already propagating).
        Such a problem must not block the install, upgrade or uninstall
        it follows, and must not stop the next step from being attempted.
        A notebook has no API-key route; the API-key policies of the
        other controllers are best effort by ruling (PR 25 review item
        2), see vectordb_controller.py.

        NOT used for creating the browser route or joining it to the
        OIDC policy: both are strict, see _ensure_gateway_route and
        _ensure_gateway_policies.
        """
        try:
            fn(*args, **kwargs)
        except Exception:
            self.logger.exception(description)

    def _ensure_gateway_route(self, instance: NotebookInstanceSchema):
        """Create/patch the browser HTTPRoute; a no-op without the gateway
        env contract (see utils/gateway.py). Notebooks get only one host.
        Strict: a failed create fails the install before
        _ensure_gateway_policies runs, so the shared OIDC policy never
        gets a targetRef to a route that does not exist.

        A create failure raises OidcPolicyError, the same type
        protect_browser_route uses for the policy step: both mean the
        notebook cannot be safely exposed, so install/upgrade must not
        mislabel either one as a Helm failure.
        """
        release = self._get_release_name(instance)
        try:
            ensure_http_route(
                instance.namespace,
                release,
                instance_hostname("nb", instance.id),
                self.get_service_name(instance),
                instance.service_port or 80,
                api_instance=self.api_instance,
            )
        except Exception as e:
            raise OidcPolicyError(
                f"HTTPRoute {instance.namespace}/{release} could not be "
                f"created: {e}"
            ) from e

    def _ensure_gateway_policies(self, instance: NotebookInstanceSchema):
        """Put the route under the shared OIDC policy (owner-only access
        is decided by the API's ext-authz endpoint) and give the kernel
        WebSockets long timeouts.

        The OIDC step is strict (fail closed): a notebook route that is
        not under the policy is a JupyterLab reachable without a login,
        so on failure protect_browser_route deletes the route again and
        raises, the install (or upgrade) fails, and the create endpoint
        marks the row Failed with the reason and uninstalls the release.
        The other steps are best effort (_safe_gateway_call).

        No appProtocol patch on the Service: the notebook-controller
        rewrites the Service ports on every reconcile (verified live, Task
        10), and Envoy speaks HTTP/1.1 to a Service without appProtocol,
        so the WebSocket upgrade works as it is."""
        namespace = instance.namespace
        release = self._get_release_name(instance)
        self._safe_gateway_call(
            f"Failed to copy the gateway client secret into {namespace}",
            ensure_gateway_client_secret,
            namespace,
            core_v1_api=self.core_v1_api,
        )
        self._safe_gateway_call(
            f"Failed to ensure the reference grants for {namespace}",
            ensure_reference_grant,
            namespace,
            api_instance=self.api_instance,
        )
        protect_browser_route(
            namespace, release, api_instance=self.api_instance
        )
        self._safe_gateway_call(
            f"Failed to ensure the backend traffic policy for {release}",
            ensure_backend_traffic_policy,
            namespace,
            release,
            api_instance=self.api_instance,
        )

    def _delete_gateway_policies(self, instance: NotebookInstanceSchema):
        """After the route (see uninstall): a policy that briefly targets
        a route that is gone is harmless, a route without its policy is
        not."""
        namespace = instance.namespace
        release = self._get_release_name(instance)
        self._safe_gateway_call(
            f"Failed to delete the backend traffic policy for {release}",
            delete_backend_traffic_policy,
            namespace,
            release,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to remove {release} from the OIDC policy",
            remove_oidc_target,
            namespace,
            release,
            api_instance=self.api_instance,
        )

    def _delete_gateway_route(self, instance: NotebookInstanceSchema):
        """The route goes first: if the Helm uninstall failed (release
        still running) it must not outlive its OIDC target. Called from a
        `finally`, where a new exception would silently replace the one
        already being propagated; see _safe_gateway_call."""
        self._safe_gateway_call(
            f"Failed to delete gateway route for {instance.id}",
            delete_http_route,
            instance.namespace,
            self._get_release_name(instance),
            api_instance=self.api_instance,
        )

    async def _add_and_update_helm_repo(
        self, instance: NotebookInstanceSchema
    ):
        repo_url = "https://infracloudio.github.io/charts"
        chart_name = "kf-notebooks"

        chart = await get_chart(self.helm, chart_name, repo=repo_url)
        self.logger.info(f"fetched chart: {chart_name} from {repo_url}")

        return chart

    async def install(self, instance: NotebookInstanceSchema):
        self.logger.debug(f"Installing instance: {instance}")
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance)

        try:
            await install_or_upgrade_release(
                self.helm,
                chart_name,
                chart,
                values,
                namespace=instance.namespace,
                create_namespace=True,
            )
            self.logger.info(f"Helm install succeeded for chart: {chart_name}")
            self._ensure_gateway_route(instance)
            self._ensure_gateway_policies(instance)
        except OidcPolicyError:
            # Helm succeeded; the gateway refused the route. Keep the
            # type and the message, the endpoints catch Exception.
            raise
        except Exception as e:
            self.logger.exception(f"Helm install failed: {str(e)}")
            raise HelmInstallError(f"Helm install failed: {str(e)}") from e

    async def upgrade(self, instance: NotebookInstanceSchema):
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance)

        try:
            await install_or_upgrade_release(
                self.helm,
                chart_name,
                chart,
                values,
                namespace=instance.namespace,
            )
            self.logger.info(f"Helm upgrade succeeded for chart: {chart_name}")
            self._ensure_gateway_route(instance)
            self._ensure_gateway_policies(instance)
        except OidcPolicyError:
            raise
        except Exception as e:
            self.logger.exception(f"Helm upgrade failed: {str(e)}")
            raise HelmUpgradeError(f"Helm upgrade failed: {str(e)}") from e

    async def uninstall(self, instance: NotebookInstanceSchema):
        chart_name = self._get_release_name(instance)

        try:
            await uninstall_release(
                self.helm, chart_name, namespace=instance.namespace
            )
            self.logger.info(
                f"Helm uninstall succeeded for chart: {chart_name}"
            )
        except ReleaseNotFoundError:
            self.logger.error(f"Release not found: {chart_name}")
        except Exception as e:
            self.logger.exception(f"Helm uninstall failed: {str(e)}")
            raise HelmUninstallError(f"Helm uninstall failed: {str(e)}") from e
        finally:
            self._delete_gateway_route(instance)
            self._delete_gateway_policies(instance)
