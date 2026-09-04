from types import SimpleNamespace
from unittest import mock

import pytest

from utils.kubernetes_utils import get_service_endpoint


def _service(service_type, *, ports=(6333,), ingress=None, cluster_ip=None):
    """Build a minimal V1Service-like object."""
    return SimpleNamespace(
        spec=SimpleNamespace(
            type=service_type,
            cluster_ip=cluster_ip,
            ports=[SimpleNamespace(port=port) for port in ports],
        ),
        status=SimpleNamespace(
            load_balancer=SimpleNamespace(ingress=ingress),
        ),
    )


def _ingress(ip=None, hostname=None):
    return [SimpleNamespace(ip=ip, hostname=hostname)]


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        pytest.param(
            _service(
                "LoadBalancer",
                ingress=_ingress(ip="203.0.113.10"),
                cluster_ip="10.96.0.10",
            ),
            "http://203.0.113.10:6333",
            id="lb-ip",
        ),
        pytest.param(
            _service(
                "LoadBalancer",
                ingress=_ingress(hostname="lb.example.test"),
                cluster_ip="10.96.0.10",
            ),
            "http://lb.example.test:6333",
            id="lb-hostname",
        ),
        pytest.param(
            _service("LoadBalancer", ingress=None, cluster_ip="10.96.0.10"),
            "http://10.96.0.10:6333",
            id="lb-pending-falls-back-to-cluster-ip",
        ),
        pytest.param(
            _service("ClusterIP", cluster_ip="10.96.0.20"),
            "http://10.96.0.20:6333",
            id="cluster-ip",
        ),
        pytest.param(
            _service("ClusterIP", ports=(), cluster_ip="10.96.0.20"),
            None,
            id="no-ports",
        ),
        pytest.param(
            _service("LoadBalancer", ingress=None, cluster_ip=None),
            None,
            id="lb-pending-without-cluster-ip",
        ),
        pytest.param(
            _service("ClusterIP", cluster_ip="None"),
            None,
            id="headless",
        ),
    ],
)
def test_get_service_endpoint(service, expected):
    core = mock.Mock()
    core.read_namespaced_service.return_value = service
    with mock.patch(
        "utils.kubernetes_utils.get_core_v1_client", return_value=core
    ):
        assert get_service_endpoint("ai-stack", "svc") == expected
    core.read_namespaced_service.assert_called_once_with(
        name="svc", namespace="ai-stack"
    )


def test_get_service_endpoint_never_contains_none():
    """Regression: a pending LoadBalancer used to yield http://None:6333."""
    core = mock.Mock()
    core.read_namespaced_service.return_value = _service(
        "LoadBalancer", ingress=None, cluster_ip=None
    )
    with mock.patch(
        "utils.kubernetes_utils.get_core_v1_client", return_value=core
    ):
        endpoint = get_service_endpoint("ai-stack", "svc")
    assert endpoint is None
