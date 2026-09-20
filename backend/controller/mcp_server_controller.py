"""Helm for an MCP server the platform deploys: one release of the
generic chart ``mcp-server``. No gateway code: only the LiteLLM proxy
talks to the pod, through the Service, and the chart's network policy
admits nobody else (ADR 0011)."""

import uuid
from dataclasses import dataclass, field

import yaml
from jinja2 import Environment, FileSystemLoader
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError

from controller.base_controller import (
    HelmInstallError,
    HelmUninstallError,
    HelmUpgradeError,
    get_chart,
    install_or_upgrade_release,
    local_chart_path,
    uninstall_release,
)
from logger import setup_logger
from paths import TEMPLATES_DIR
from utils import mcp_instances
from utils.kubernetes_utils import get_core_v1_client, get_default_namespace
from utils.mcp_catalog_settings import env_values, render_args
from utils.render_guard import refuse_line_breaks

VALUES_TEMPLATE = "mcp-server-values.yaml.jinja"


@dataclass(frozen=True)
class DeploySpec:
    """Everything a release is made from, as plain data: the async Helm
    calls never touch a database row."""

    instance_id: uuid.UUID
    image: str
    tag: str
    port: int
    path: str
    egress: str
    chart_repo: str
    chart_name: str
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    # The catalog entry's settings, and the plain values an admin gave.
    schema: list[dict] = field(default_factory=list)
    plain: dict[str, str] = field(default_factory=dict)
    # The Secret with the secret settings; "" when there are none.
    env_secret: str = ""
    checksum: str = ""


class McpServerController:
    def __init__(
        self,
        namespace: str | None = None,
        core_v1_api=None,
        helm_client: HelmClient | None = None,
    ):
        self.logger = setup_logger(__name__)
        # Loads the kube config: an unreachable cluster fails here,
        # before any row exists.
        self.core_v1_api = core_v1_api or get_core_v1_client()
        self.namespace = namespace or get_default_namespace()
        self.helm = helm_client or HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

    def release_name(self, instance_id: uuid.UUID) -> str:
        return mcp_instances.release_name(instance_id)

    def get_pod_labels(self, spec_or_row) -> str:
        instance_id = (
            getattr(spec_or_row, "instance_id", None) or spec_or_row.id
        )
        return (
            f"app.kubernetes.io/instance={self.release_name(instance_id)},"
            "app.kubernetes.io/name=mcp-server"
        )

    def service_url(self, spec: DeploySpec) -> str:
        return mcp_instances.service_url(
            spec.instance_id, self.namespace, spec.port, spec.path
        )

    def prepare_helm_values(self, spec: DeploySpec) -> dict:
        proxy_namespace, proxy_labels = mcp_instances.proxy_selector()
        host = mcp_instances.service_host(spec.instance_id, self.namespace)
        context = {
            "release_name": self.release_name(spec.instance_id),
            "image": spec.image,
            "tag": spec.tag,
            "command": list(spec.command),
            "args": render_args(
                spec.args,
                spec.schema,
                spec.plain,
                host=host,
                port=str(spec.port),
                path=spec.path,
            ),
            "port": spec.port,
            "env": env_values(spec.schema, spec.plain),
            "env_from_secret": spec.env_secret,
            "settings_checksum": spec.checksum,
            "proxy_namespace": proxy_namespace,
            "proxy_labels": proxy_labels,
            "egress": spec.egress,
        }
        refuse_line_breaks(context)
        rendered = self.jinja_env.get_template(VALUES_TEMPLATE).render(context)
        return yaml.safe_load(rendered)

    async def _chart(self, spec: DeploySpec):
        # The checkout's chart first (AIOPS_CHARTS_DIR): a chart can be
        # tried before it is published.
        local = local_chart_path(spec.chart_name)
        if local is not None:
            return await get_chart(self.helm, str(local))
        return await get_chart(
            self.helm, spec.chart_name, repo=spec.chart_repo
        )

    async def install(self, spec: DeploySpec) -> None:
        values = self.prepare_helm_values(spec)
        name = self.release_name(spec.instance_id)
        try:
            chart = await self._chart(spec)
            await install_or_upgrade_release(
                self.helm,
                name,
                chart,
                values,
                namespace=self.namespace,
                create_namespace=True,
            )
            self.logger.info(f"Helm install succeeded for {name}")
        except Exception as e:
            self.logger.exception(f"Helm install failed: {e}")
            raise HelmInstallError(f"Helm install failed: {e}") from e

    async def upgrade(self, spec: DeploySpec) -> None:
        values = self.prepare_helm_values(spec)
        name = self.release_name(spec.instance_id)
        try:
            chart = await self._chart(spec)
            await install_or_upgrade_release(
                self.helm, name, chart, values, namespace=self.namespace
            )
            self.logger.info(f"Helm upgrade succeeded for {name}")
        except Exception as e:
            self.logger.exception(f"Helm upgrade failed: {e}")
            raise HelmUpgradeError(f"Helm upgrade failed: {e}") from e

    async def uninstall(self, instance_id: uuid.UUID) -> None:
        name = self.release_name(instance_id)
        try:
            await uninstall_release(self.helm, name, namespace=self.namespace)
            self.logger.info(f"Helm uninstall succeeded for {name}")
        except ReleaseNotFoundError:
            # A release that is gone is what a delete wants.
            self.logger.info(f"Release not found: {name}")
        except Exception as e:
            self.logger.exception(f"Helm uninstall failed: {e}")
            raise HelmUninstallError(f"Helm uninstall failed: {e}") from e
