from kubernetes import config
from fastapi import HTTPException

def load_kubernetes_config():
    try:
        config.load_kube_config()
        return "kube_config"
    except config.config_exception.ConfigException:
        try:
            config.load_incluster_config()
            return "incluster_config"
        except config.config_exception.ConfigException:
            raise HTTPException(status_code=500, detail="Failed to load Kubernetes configuration")
