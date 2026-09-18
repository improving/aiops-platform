from pydantic import BaseModel


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
    gpu_usage: float
    # What the node offers to pods (status.allocatable) and what the pods
    # on it already ask for (container requests of Pending and Running
    # pods), so a launch form can show what is free. Memory in MiB, like
    # gpu_memory; CPU in cores. The defaults are what a node without these numbers reports.
    allocatable_cpu: float = 0.0
    allocatable_memory: int = 0
    allocatable_gpu: float = 0.0
    requested_cpu: float = 0.0
    requested_memory: int = 0
