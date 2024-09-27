from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes import client

from logger import setup_logger
from models.hosts import Host
from utils.kubernetes_utils import get_kubernetes_client

logger = setup_logger(__name__)

router = APIRouter()


# API to get host information
@router.get("/v1alpha1/hosts", response_model=List[Host])
def get_hosts(includeNotReady: bool = Query(
    default=False, description="Include nodes that are not in Ready status"),
              v1: client.CoreV1Api = Depends(get_kubernetes_client,
                                             use_cache=True)):
    try:
        nodes = v1.list_node()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    hosts = []
    for node in nodes.items:
        # Check if the node is in Ready status
        is_ready = any(condition.type == "Ready" and condition.status == "True"
                       for condition in node.status.conditions)

        if is_ready or includeNotReady:
            labels = node.metadata.labels or {}

            host = Host(
                hostname=labels.get("kubernetes.io/hostname", "Unknown"),
                cpu_vendor=labels.get(
                    "feature.node.kubernetes.io/cpu-model.vendor_id",
                    "Unknown"),
                cpu_memory=labels.get(
                    "feature.node.kubernetes.io/cpu-model.memory", "0"),
                cpu_cores=labels.get(
                    "feature.node.kubernetes.io/cpu-model.cores", "0"),
                cuda_driver_version=labels.get(
                    "nvidia.com/cuda.driver-version.full", "N/A"),
                cuda_runtime_version=labels.get(
                    "nvidia.com/cuda.runtime-version.full", "N/A"),
                gpu_count=int(labels.get("nvidia.com/gpu.count", 0)),
                gpu_memory=int(labels.get("nvidia.com/gpu.memory", 0)),
                gpu_model=labels.get("nvidia.com/gpu.product", "N/A"),
                gpu_replicas=int(
                    labels.get("nvidia.com/gpu.replicas",
                               int(labels.get("nvidia.com/gpu.memory", 0)))),
                gpu_sharing_strategy=labels.get(
                    "nvidia.com/gpu.sharing-strategy", "N/A"),
            )
            hosts.append(host)

    return hosts
