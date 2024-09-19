from fastapi import HTTPException
from kubernetes import client, config

from logger import setup_logger

# Initialize the logger
logger = setup_logger(__name__)

def load_kubernetes_config():
    try:
        config.load_kube_config()
        return "kube_config"
    except config.config_exception.ConfigException:
        try:
            config.load_incluster_config()
            return "incluster_config"
        except config.config_exception.ConfigException:
            raise HTTPException(
                status_code=500,
                detail="Failed to load Kubernetes configuration")


def get_kubernetes_client():
    load_kubernetes_config()
    return client.CoreV1Api()

def get_pod_status_and_readiness(namespace, pod_labels):
    try:
        core_v1_api = get_kubernetes_client()
        # Query pods
        pods = core_v1_api.list_namespaced_pod(namespace=namespace,
                                               label_selector=pod_labels)

        # Check if any pod is ready
        instance_ready = any(pod.status.phase == 'Running' and all(
            container.ready for container in pod.status.container_statuses)
                             for pod in pods.items)

        if pods.items:
            pod = pods.items[0]
            status = pod.status.container_statuses[0]
            if pod.status.init_container_statuses:
                initContainerStatus = pod.status.init_container_statuses[0]
                if not initContainerStatus.state.terminated:
                    logger.info("Using init container status")
                    status = initContainerStatus
                else:
                    logger.info("Using container status")

            logger.debug(f"Pod Name: {pod.metadata.name}, Status: {status}")
            if not status.started and status.state.waiting:
                instance_status = status.state.waiting.reason
            elif not status.started and status.state.terminated:
                instance_status = "Terminated"
            elif status.started or (not status.started
                                    and status.state.running.started_at):
                instance_status = "Running"
            else:
                instance_status = status.state
        else:
            instance_status = "Unknown"
    except client.exceptions.ApiException as e:
        logger.exception(f"Error checking pod status and readiness: {e}")
        instance_ready = False
        instance_status = "Unknown"

    return instance_ready, instance_status

def get_service_endpoint(namespace, service_name):
    endpoint = None
    try:
        # Get the service information
        service = get_kubernetes_client().read_namespaced_service(
            name=service_name, namespace=namespace)

        # Get the service IP and port
        if service.spec.type == "LoadBalancer":
            ip = service.status.load_balancer.ingress[
                0].ip if service.status.load_balancer.ingress else None
        else:
            ip = service.spec.cluster_ip

        port = service.spec.ports[0].port if service.spec.ports else None

        if not (ip and port):
            logger.warning(
                f"Warning: Could not determine IP or port for service {service_name}"
            )
        endpoint = f"http://{ip}:{port}"
    except client.exceptions.ApiException as e:
        logger.exception(f"Error getting service information: {e}")

    return endpoint
