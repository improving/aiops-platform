import base64

import yaml
from jinja2 import Environment, FileSystemLoader
from kubernetes import client
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError

from controller.base_controller import (
    HelmInstallError,
    HelmUninstallError,
    HelmUpgradeError,
    get_chart,
    install_or_upgrade_release,
    uninstall_release,
)
from logger import setup_logger
from paths import TEMPLATES_DIR
from schemas.vectordb_instance import VectorDBInstanceSchema
from utils.credentials import CREDENTIAL_KEY, credential_secret_names
from utils.gateway import (
    add_oidc_target,
    apikey_secret_name,
    delete_http_route,
    delete_security_policy,
    ensure_gateway_client_secret,
    ensure_http_route,
    ensure_reference_grant,
    ensure_security_policy,
    instance_hostname,
    remove_oidc_target,
)
from utils.kubernetes_utils import get_core_v1_client, get_default_namespace

# Gateway port per chart: the port each vector DB serves its REST/gRPC API
# (and, where it has one, its browser dashboard) on.
VECTORDB_GATEWAY_PORTS = {
    "qdrant": 6333,
    "chromadb": 8000,
    "milvus": 19530,
}


class VectorDBController:
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

    def _get_release_name(self, instance: VectorDBInstanceSchema):
        return f"{instance.vectorDB.chart_name.lower()}-{str(instance.id)[:8]}"

    def get_service_name(self, instance: VectorDBInstanceSchema):
        return f"{self._get_release_name(instance)}"

    def get_pod_labels(self, instance: VectorDBInstanceSchema):
        return (
            f"app.kubernetes.io/instance={self._get_release_name(instance)},"
            f"app.kubernetes.io/name={instance.vectorDB.chart_name}"
        )

    async def prepare_helm_values(
        self,
        instance: VectorDBInstanceSchema,
        credential: str | None = None,
    ):
        """Render the chart values.

        ``credential`` is the instance API key from utils/credentials.py;
        the templates turn it into the chart's own auth setting (the
        Qdrant ``apiKey`` Secret reference, the Milvus root password)
        and leave it out when it is None.
        """
        template = self.jinja_env.get_template(
            f"{instance.vectorDB.chart_name.lower()}-values.yaml.jinja"
        )

        context = self._get_base_context(instance, credential)

        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        return values

    def _get_base_context(
        self,
        instance: VectorDBInstanceSchema,
        credential: str | None = None,
    ):
        service_type = None
        if instance.configParams:
            service_type = instance.configParams.get("serviceType")

        secret_name = None
        if credential is not None:
            secret_name, _ = credential_secret_names("vdb", instance.id)
        return {
            "service_type": service_type or "ClusterIP",
            "credential": credential,
            "credential_secret_name": secret_name,
        }

    def _read_credential(self, instance: VectorDBInstanceSchema) -> str | None:
        """The stored API key, from the credentials Secret; None when the
        instance has none (created before credentials existed)."""
        secret_name, _ = credential_secret_names("vdb", instance.id)
        try:
            secret = self.core_v1_api.read_namespaced_secret(
                name=secret_name, namespace=self.namespace
            )
        except client.exceptions.ApiException as e:
            if e.status == 404:
                return None
            raise
        encoded = (secret.data or {}).get(CREDENTIAL_KEY)
        if encoded is None:
            return None
        return base64.b64decode(encoded).decode("utf-8")

    async def _add_and_update_helm_repo(
        self, instance: VectorDBInstanceSchema
    ):
        repo_url = instance.vectorDB.chart_repo
        chart_name = instance.vectorDB.chart_name

        chart = await get_chart(self.helm, chart_name, repo=repo_url)
        self.logger.info(f"fetched chart: {chart_name} from {repo_url}")

        return chart

    def _gateway_port(self, instance: VectorDBInstanceSchema) -> int:
        return VECTORDB_GATEWAY_PORTS.get(
            instance.vectorDB.chart_name.lower(), 80
        )

    def _gateway_route_names(self, instance: VectorDBInstanceSchema):
        release = self._get_release_name(instance)
        return release, f"{release}-api"

    def _safe_gateway_call(self, description: str, fn, *args, **kwargs):
        """Run one gateway call, logging instead of raising on failure.

        Never raises: a route problem must not be mistaken for a Helm
        failure (which would leave the release installed but the row
        deleted, since the caller's except-and-delete does not know the
        difference), must not block the install/upgrade/uninstall it
        follows, and must not stop a *second* route (e.g. the "-api" host)
        from being attempted when the first one fails.
        """
        try:
            fn(*args, **kwargs)
        except Exception:
            self.logger.exception(description)

    def _ensure_gateway_routes(self, instance: VectorDBInstanceSchema):
        """Create/patch the browser and SDK HTTPRoutes; a no-op without the
        gateway env contract (see utils/gateway.py)."""
        service_name = self.get_service_name(instance)
        port = self._gateway_port(instance)
        browser_name, api_name = self._gateway_route_names(instance)
        self._safe_gateway_call(
            f"Failed to ensure gateway route {browser_name} for {instance.id}",
            ensure_http_route,
            self.namespace,
            browser_name,
            instance_hostname("vdb", instance.id),
            service_name,
            port,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to ensure gateway route {api_name} for {instance.id}",
            ensure_http_route,
            self.namespace,
            api_name,
            instance_hostname("vdb", instance.id, suffix="-api"),
            service_name,
            port,
            api_instance=self.api_instance,
        )

    def _apikey_policy_name(self, instance: VectorDBInstanceSchema) -> str:
        _, api_name = self._gateway_route_names(instance)
        return f"{api_name}-apikey"

    def _ensure_gateway_policies(self, instance: VectorDBInstanceSchema):
        """The dashboard host joins the shared OIDC policy; the SDK host
        gets an API-key policy reading the credential Secret that the
        create endpoint stores before installing (utils/credentials.py).
        Each step is attempted on its own."""
        browser_name, api_name = self._gateway_route_names(instance)
        self._safe_gateway_call(
            f"Failed to copy the gateway client secret into {self.namespace}",
            ensure_gateway_client_secret,
            self.namespace,
            core_v1_api=self.core_v1_api,
        )
        self._safe_gateway_call(
            f"Failed to ensure the reference grants for {self.namespace}",
            ensure_reference_grant,
            self.namespace,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to add {browser_name} to the OIDC policy",
            add_oidc_target,
            self.namespace,
            browser_name,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to ensure the API-key policy for {api_name}",
            ensure_security_policy,
            self.namespace,
            self._apikey_policy_name(instance),
            api_name,
            "apikey",
            instance_hostname("vdb", instance.id, suffix="-api"),
            apikey_secret_name("vdb", instance.id),
            api_instance=self.api_instance,
        )

    def _delete_gateway_policies(self, instance: VectorDBInstanceSchema):
        """Policies go before the routes they target."""
        browser_name, api_name = self._gateway_route_names(instance)
        self._safe_gateway_call(
            f"Failed to remove {browser_name} from the OIDC policy",
            remove_oidc_target,
            self.namespace,
            browser_name,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to delete the API-key policy for {api_name}",
            delete_security_policy,
            self.namespace,
            self._apikey_policy_name(instance),
            api_instance=self.api_instance,
        )

    def _delete_gateway_routes(self, instance: VectorDBInstanceSchema):
        """Called from a `finally`, where a new exception would silently
        replace the one already being propagated; see _safe_gateway_call."""
        browser_name, api_name = self._gateway_route_names(instance)
        self._safe_gateway_call(
            f"Failed to delete gateway route {browser_name} for {instance.id}",
            delete_http_route,
            self.namespace,
            browser_name,
            api_instance=self.api_instance,
        )
        self._safe_gateway_call(
            f"Failed to delete gateway route {api_name} for {instance.id}",
            delete_http_route,
            self.namespace,
            api_name,
            api_instance=self.api_instance,
        )

    async def install(
        self,
        instance: VectorDBInstanceSchema,
        credential: str | None = None,
    ):
        """Install the chart; ``credential`` is the API key the caller has
        just stored (its Secrets must exist before the Helm install, the
        Qdrant chart looks the value up at render time)."""
        self.logger.debug(f"Installing instance: {instance}")
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance, credential)

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
            self._ensure_gateway_routes(instance)
            self._ensure_gateway_policies(instance)
        except (
            Exception
        ) as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm install failed: {str(e)}")
            raise HelmInstallError(
                f"Helm install failed: {str(e)}"
            ) from e  # {{ edit_1 }}

    async def upgrade(
        self,
        instance: VectorDBInstanceSchema,
        credential: str | None = None,
    ):
        """Upgrade the release; without ``credential`` the stored key is
        read back from its Secret, so an upgrade keeps the auth values."""
        if credential is None:
            credential = self._read_credential(instance)
        chart = await self._add_and_update_helm_repo(instance)
        chart_name = self._get_release_name(instance)
        values = await self.prepare_helm_values(instance, credential)

        try:
            await install_or_upgrade_release(
                self.helm, chart_name, chart, values, namespace=self.namespace
            )
            self.logger.info(f"Helm upgrade succeeded for chart: {chart_name}")
            self._ensure_gateway_routes(instance)
            self._ensure_gateway_policies(instance)
        except (
            Exception
        ) as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm upgrade failed: {str(e)}")
            raise HelmUpgradeError(f"Helm upgrade failed: {str(e)}") from e

    async def uninstall(self, instance: VectorDBInstanceSchema):
        chart_name = self._get_release_name(instance)

        try:
            await uninstall_release(
                self.helm, chart_name, namespace=self.namespace
            )
            self.logger.info(
                f"Helm uninstall succeeded for chart: {chart_name}"
            )
        except ReleaseNotFoundError:
            self.logger.error(f"Release not found: {chart_name}")
        except (
            Exception
        ) as e:  # Consider replacing with a more specific exception
            self.logger.exception(f"Helm uninstall failed: {str(e)}")
            raise HelmUninstallError(f"Helm uninstall failed: {str(e)}") from e
        finally:
            self._delete_gateway_policies(instance)
            self._delete_gateway_routes(instance)
