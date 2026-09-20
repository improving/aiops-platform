"""The controller of a deployed MCP server: the values it renders, and
that nothing an admin types can add a key to them."""

import asyncio
import uuid
from unittest import mock

import pytest
import yaml
from pyhelm3.errors import ReleaseNotFoundError

from controller import mcp_server_controller as module
from controller.mcp_server_controller import DeploySpec, McpServerController
from paths import RAW_DATA_DIR
from utils import mcp_instances
from utils.mcp_catalog_settings import normal_setting

INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-0000abcd1234")
GRAFANA = yaml.safe_load((RAW_DATA_DIR / "mcp_catalog.yaml").read_text())[
    "entries"
][0]


@pytest.fixture(autouse=True)
def proxy(monkeypatch):
    monkeypatch.setenv("AIOPS_LITELLM_NAMESPACE", "litellm")
    monkeypatch.setenv(
        "AIOPS_LITELLM_POD_LABELS",
        "app.kubernetes.io/name=litellm,app.kubernetes.io/instance=litellm",
    )
    monkeypatch.delenv("AIOPS_CHARTS_DIR", raising=False)


def _controller(helm=None):
    return McpServerController(
        namespace="ai-stack",
        core_v1_api=mock.Mock(),
        helm_client=helm or mock.Mock(),
    )


def _spec(**overrides):
    values = {
        "instance_id": INSTANCE_ID,
        "image": GRAFANA["image"],
        "tag": GRAFANA["tag"],
        "port": GRAFANA["port"],
        "path": GRAFANA["path"],
        "egress": GRAFANA["egress"],
        "chart_repo": GRAFANA["chart_repo"],
        "chart_name": GRAFANA["chart_name"],
        "args": GRAFANA["args"],
        "schema": [normal_setting(s) for s in GRAFANA["settings"]],
        "plain": {
            "GRAFANA_URL": "http://grafana.monitoring.svc:3000",
            "READ_ONLY": "true",
        },
        "env_secret": "mcpi-abcd1234-env",
        "checksum": "c0ffee",
    }
    values.update(overrides)
    return DeploySpec(**values)


def test_the_values_of_the_grafana_entry(snapshot):
    values = _controller().prepare_helm_values(_spec())
    assert values["fullnameOverride"] == "mcpi-abcd1234"
    # The Service host, for the server's Host check; the switch is an
    # argument and never an environment variable.
    assert values["args"][-3:] == [
        "-allowed-hosts",
        "mcpi-abcd1234.ai-stack.svc,mcpi-abcd1234.ai-stack.svc:8000",
        "-disable-write",
    ]
    assert values["env"] == [
        {"name": "GRAFANA_URL", "value": "http://grafana.monitoring.svc:3000"}
    ]
    assert values["networkPolicy"]["ingressFrom"] == {
        "namespace": "litellm",
        "podLabels": {
            "app.kubernetes.io/name": "litellm",
            "app.kubernetes.io/instance": "litellm",
        },
    }
    snapshot.snapshot_dir = "snapshots/test_mcp_controller"
    snapshot.assert_match(
        yaml.safe_dump(values, sort_keys=True), "grafana-values.yaml"
    )


def test_a_switch_that_is_off_adds_no_argument():
    values = _controller().prepare_helm_values(
        _spec(plain={"GRAFANA_URL": "http://g:3000", "READ_ONLY": "false"})
    )
    assert "-disable-write" not in values["args"]


def test_a_value_cannot_add_keys_to_the_rendered_values():
    hostile = 'x"\nimage:\n  repository: evil'
    with pytest.raises(ValueError, match="line break"):
        _controller().prepare_helm_values(
            _spec(plain={"GRAFANA_URL": hostile})
        )
    quoted = 'http://g:3000", "x": "y'
    values = _controller().prepare_helm_values(
        _spec(plain={"GRAFANA_URL": quoted})
    )
    assert values["env"][0]["value"] == quoted
    assert values["image"]["repository"] == GRAFANA["image"]


def test_without_the_proxys_selector_nothing_is_rendered(monkeypatch):
    monkeypatch.delenv("AIOPS_LITELLM_POD_LABELS")
    with pytest.raises(mcp_instances.ProxySelectorError, match="every pod"):
        _controller().prepare_helm_values(_spec())
    monkeypatch.setenv("AIOPS_LITELLM_POD_LABELS", "no equals sign")
    with pytest.raises(mcp_instances.ProxySelectorError, match="label=value"):
        _controller().prepare_helm_values(_spec())
    monkeypatch.setenv("AIOPS_LITELLM_POD_LABELS", "a=b")
    monkeypatch.setenv("AIOPS_LITELLM_NAMESPACE", "Not A Namespace")
    with pytest.raises(mcp_instances.ProxySelectorError, match="namespace"):
        _controller().prepare_helm_values(_spec())


def test_the_checkouts_chart_wins_and_a_missing_release_is_fine(
    monkeypatch, tmp_path
):
    (tmp_path / "mcp-server").mkdir()
    (tmp_path / "mcp-server" / "Chart.yaml").write_text("name: mcp-server\n")
    monkeypatch.setenv("AIOPS_CHARTS_DIR", str(tmp_path))
    asked = {}

    async def get_chart(helm, ref, repo=None):
        asked.update(ref=ref, repo=repo)
        return "chart"

    install = mock.AsyncMock()
    monkeypatch.setattr(module, "get_chart", get_chart)
    monkeypatch.setattr(module, "install_or_upgrade_release", install)
    controller = _controller()
    asyncio.run(controller.install(_spec()))
    assert asked == {"ref": str(tmp_path / "mcp-server"), "repo": None}
    assert install.call_args.args[1] == "mcpi-abcd1234"
    assert install.call_args.kwargs["namespace"] == "ai-stack"

    monkeypatch.setattr(
        module,
        "uninstall_release",
        mock.AsyncMock(side_effect=ReleaseNotFoundError(1, b"", b"not found")),
    )
    asyncio.run(controller.uninstall(INSTANCE_ID))
    monkeypatch.setattr(
        module,
        "uninstall_release",
        mock.AsyncMock(side_effect=RuntimeError("x")),
    )
    with pytest.raises(module.HelmUninstallError):
        asyncio.run(controller.uninstall(INSTANCE_ID))


def test_names_use_the_last_eight_characters():
    assert mcp_instances.release_name(INSTANCE_ID) == "mcpi-abcd1234"
    assert mcp_instances.env_secret_name(INSTANCE_ID) == "mcpi-abcd1234-env"
    assert (
        mcp_instances.service_url(INSTANCE_ID, "ai-stack", 8000, "/mcp")
        == "http://mcpi-abcd1234.ai-stack.svc:8000/mcp"
    )
