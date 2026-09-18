from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes import client
from kubernetes.utils import parse_quantity

from auth.current_user import CurrentUser, get_current_user
from logger import setup_logger
from models.hosts import Host
from utils.kubernetes_utils import get_core_v1_client

logger = setup_logger(__name__)

router = APIRouter()


# API to get host information
@router.get("/v1alpha1/hosts", response_model=list[Host])
def get_hosts(
    includeNotReady: bool = Query(
        default=False, description="Include nodes that are not in Ready status"
    ),
    v1: client.CoreV1Api = Depends(get_core_v1_client, use_cache=True),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Retrieve information about Kubernetes hosts.

    Args:
        includeNotReady (bool): If True, include nodes that are not in Ready status.

    Returns:
        List[Host]: A list of Host objects containing information about each node.

    Raises:
        HTTPException: If there's an error retrieving node information from Kubernetes.
    """
    try:
        nodes = v1.list_node()
        usage_per_node = get_node_usage(v1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    hosts = []
    for node in nodes.items:
        # Check if the node is in Ready status
        is_ready = any(
            condition.type == "Ready" and condition.status == "True"
            for condition in node.status.conditions
        )

        if is_ready or includeNotReady:
            labels = node.metadata.labels or {}
            usage = usage_per_node.get(node.metadata.name, {})
            allocatable = node.status.allocatable or {}

            host = Host(
                hostname=labels.get("kubernetes.io/hostname", "Unknown"),
                cpu_vendor=labels.get(
                    "feature.node.kubernetes.io/cpu-model.vendor_id", "Unknown"
                ),
                cpu_memory=labels.get(
                    "feature.node.kubernetes.io/cpu-model.memory", "0"
                ),
                cpu_cores=labels.get(
                    "feature.node.kubernetes.io/cpu-model.cores", "0"
                ),
                cuda_driver_version=labels.get(
                    "nvidia.com/cuda.driver-version.full", "N/A"
                ),
                cuda_runtime_version=labels.get(
                    "nvidia.com/cuda.runtime-version.full", "N/A"
                ),
                gpu_count=int(labels.get("nvidia.com/gpu.count", 0)),
                gpu_memory=int(labels.get("nvidia.com/gpu.memory", 0)),
                gpu_model=labels.get("nvidia.com/gpu.product", "N/A"),
                # Without time-slicing there is no such label: one GPU is
                # one replica.
                gpu_replicas=int(labels.get("nvidia.com/gpu.replicas", 1)),
                gpu_sharing_strategy=labels.get(
                    "nvidia.com/gpu.sharing-strategy", "N/A"
                ),
                gpu_usage=usage.get("gpu", 0),
                allocatable_cpu=round(_quantity(allocatable.get("cpu", 0)), 3),
                allocatable_memory=int(
                    _quantity(allocatable.get("memory", 0)) // _MIB
                ),
                allocatable_gpu=_quantity(
                    allocatable.get("nvidia.com/gpu", 0)
                ),
                requested_cpu=round(usage.get("cpu", 0), 3),
                requested_memory=int(usage.get("memory", 0) // _MIB),
            )
            hosts.append(host)

    return hosts


# Pods in these phases hold their requests on the node; a Succeeded or
# Failed pod stays in the listing and holds nothing.
_HOLDING_PHASES = ("Pending", "Running")
_MIB = 1024 * 1024


def _quantity(value) -> float:
    """A Kubernetes quantity ("500m", "16Gi", "4") as a number; 0 for
    anything unreadable, so one odd pod does not fail the whole listing."""
    try:
        return float(parse_quantity(value))
    except (ValueError, TypeError):
        return 0.0


def get_node_usage(v1: client.CoreV1Api) -> dict[str, dict[str, float]]:
    """What the pods on each node ask for, keyed by node name:
    ``{"cpu": cores, "memory": bytes, "gpu": devices}``, summed over the
    container requests of the pods that hold them. One listing for the
    whole cluster."""
    usage: dict[str, dict[str, float]] = {}
    for pod in v1.list_pod_for_all_namespaces().items:
        node_name = pod.spec.node_name
        if not node_name or pod.status.phase not in _HOLDING_PHASES:
            continue
        node = usage.setdefault(
            node_name, {"cpu": 0.0, "memory": 0.0, "gpu": 0.0}
        )
        for container in pod.spec.containers:
            requests = (
                container.resources.requests if container.resources else None
            ) or {}
            node["cpu"] += _quantity(requests.get("cpu", 0))
            node["memory"] += _quantity(requests.get("memory", 0))
            node["gpu"] += _quantity(requests.get("nvidia.com/gpu", 0))
    logger.debug(f"Requests per node: {usage}")
    return usage
