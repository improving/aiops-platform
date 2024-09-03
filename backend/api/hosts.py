from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from kubernetes import client, config
from typing import List, Dict

router = APIRouter()

# Pydantic model for Host
class Host(BaseModel):
    hostname: str
    cpu_vendor: str
    cpu_memory: int
    cpu_cores: int
    cuda_driver_version: str
    cuda_runtime_version: str
    gpu_count: int
    gpu_memory: int
    gpu_model: str
    gpu_replicas: int
    gpu_sharing_strategy: str

# Load Kubernetes configuration
config.load_kube_config()  # Use load_incluster_config() if running inside a pod

# API to get host information
@router.get("/v1alpha1/hosts", response_model=List[Host])
def get_hosts():
    v1 = client.CoreV1Api()
    try:
        nodes = v1.list_node()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    hosts = []
    for node in nodes.items:
        labels = node.metadata.labels or {}
        host = Host(
            hostname=labels.get("kubernetes.io/hostname", "Unknown"),
            cpu_vendor=labels.get("feature.node.kubernetes.io/cpu-model.vendor_id", "Unknown"),
            cpu_memory=labels.get("feature.node.kubernetes.io/cpu-model.memory", "0"),
            cpu_cores=labels.get("feature.node.kubernetes.io/cpu-model.cores", "0"),
            cuda_driver_version=labels.get("nvidia.com/cuda.driver-version.full", "N/A"),
            cuda_runtime_version=labels.get("nvidia.com/cuda.runtime-version.full", "N/A"),
            gpu_count=int(labels.get("nvidia.com/gpu.count", 0)),
            gpu_memory=int(labels.get("nvidia.com/gpu.memory", 0)),
            gpu_model=labels.get("nvidia.com/gpu.product", "N/A"),
            gpu_replicas=int(labels.get("nvidia.com/gpu.replicas", int(labels.get("nvidia.com/gpu.memory", 0)))),
            gpu_sharing_strategy=labels.get("nvidia.com/gpu.sharing-strategy", "N/A"),
        )
        hosts.append(host)

    return hosts


def get_host_details(hostname: str) -> dict:
    v1 = client.CoreV1Api()
    try:
        nodes = v1.list_node()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    for node in nodes.items:
        if node.metadata.annotations and node.metadata.annotations.get("kubernetes.io/hostname") == hostname:
            annotations = node.metadata.annotations
            return {
                "cpu_vendor": annotations.get("feature.node.kubernetes.io/cpu-model.vendor_id", "Unknown"),
                "cuda_driver_version": annotations.get("nvidia.com/cuda.driver-version.full", "N/A"),
                "cuda_runtime_version": annotations.get("nvidia.com/cuda.runtime-version.full", "N/A"),
                "gpu_count": int(annotations.get("nvidia.com/gpu.count", 0)),
                "gpu_memory": int(annotations.get("nvidia.com/gpu.memory", 0)),
                "gpu_model": annotations.get("nvidia.com/gpu.product", "N/A"),
                "gpu_replicas": int(annotations.get("nvidia.com/gpu.replicas", 0)),
                "gpu_sharing_strategy": annotations.get("nvidia.com/gpu.sharing-strategy", "N/A"),
            }
    return {}