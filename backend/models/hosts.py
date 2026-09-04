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
