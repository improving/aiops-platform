from fastapi import HTTPException
from kubernetes import client, config
from urllib3.util.retry import Retry

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


def get_core_v1_client():
    api_client = get_kubernetes_api_client()
    return client.CoreV1Api(api_client)


def get_batch_v1_client():
    api_client = get_kubernetes_api_client()
    return client.BatchV1Api(api_client=api_client)


def get_kubernetes_api_client():
    load_kubernetes_config()
    configuration = client.Configuration.get_default_copy()
    configuration.client_side_validation = False
    configuration.timeout = 2
    retry = Retry(total=3,
                  backoff_factor=1,
                  status_forcelist=[500, 502, 503, 504])
    configuration.retries = retry
    api_client = client.ApiClient(configuration)
    return api_client


def submit_job(namespace, job: client.V1Job):
    job_client = get_batch_v1_client()
    try:
        job_client.create_namespaced_job(namespace=namespace, body=job)
    except client.exceptions.ApiException as e:
        logger.exception(f"Error creating job: {e}")
        raise


def delete_job(namespace, job_name):
    job_client = get_batch_v1_client()
    try:
        job_client.delete_namespaced_job(
            namespace=namespace,
            name=job_name,
            body=client.V1DeleteOptions(propagation_policy="Foreground"))
        logger.info(f"Job {job_name} deleted successfully")
    except client.exceptions.ApiException as e:
        logger.exception(f"Error deleting job: {e}")
        raise


def create_config_map(namespace, config_map):
    core_v1_api = get_core_v1_client()
    try:
        core_v1_api.create_namespaced_config_map(namespace=namespace,
                                                 body=config_map)
        logger.info(
            f"ConfigMap {config_map.metadata.name} created successfully")
    except client.exceptions.ApiException as e:
        logger.exception(f"Error creating config map: {e}")
        raise


def delete_config_map(namespace, config_map_name):
    core_v1_api = get_core_v1_client()
    try:
        core_v1_api.delete_namespaced_config_map(namespace=namespace,
                                                 name=config_map_name)
        logger.info(f"ConfigMap {config_map_name} deleted successfully")
    except client.exceptions.ApiException as e:
        logger.exception(f"Error deleting config map: {e}")
        raise


def get_pod_status_and_readiness(namespace, pod_labels):
    try:
        core_v1_api = get_core_v1_client()
        # Query pods
        pods = core_v1_api.list_namespaced_pod(namespace=namespace,
                                               label_selector=pod_labels)

        # Check if any pod is ready
        instance_ready = any(pod.status.phase == 'Running' and all(
            container.ready for container in pod.status.container_statuses)
                             for pod in pods.items)

        instance_status = "Unknown"
        if pods.items:
            pod = pods.items[0]
            container_status = get_container_status_obj(pod)

            if container_status:
                logger.debug(
                    f"Pod Name: {pod.metadata.name}, Status: {container_status}"
                )
                if not container_status.started and container_status.state.waiting:
                    instance_status = container_status.state.waiting.reason
                elif not container_status.started and container_status.state.terminated:
                    instance_status = "Terminated"
                elif container_status.started or (
                        not container_status.started
                        and container_status.state.running.started_at):
                    instance_status = "Running"
                else:
                    instance_status = container_status.state
    except client.exceptions.ApiException as e:
        logger.exception(f"Error checking pod status and readiness: {e}")
        instance_ready = False
        instance_status = "Unknown"

    return instance_ready, instance_status


async def get_job_status(job_name, namespace):
    job_client = get_batch_v1_client()
    job_status = "Unknown"
    try:
        job = job_client.read_namespaced_job_status(name=job_name,
                                                    namespace=namespace)
        if job:
            job_status = interpret_job_status(job.status)

        return job_status
    except client.ApiException as e:
        logger.error(f"Error getting job status: {e}")
        raise


def interpret_job_status(job_status):
    status = "Running"

    if job_status.conditions:
        for condition in job_status.conditions:
            if condition.type == "Complete":
                status = "Completed" if condition.status == "True" else "Failed"
                break
            if condition.type == "Failed":
                status = "Failed"
                break

    return status


async def get_job_logs(job_name, namespace):
    core_client = get_core_v1_client()
    logs = "No logs available"
    try:
        pods = core_client.list_namespaced_pod(
            namespace=namespace, label_selector=f"job-name={job_name}")
        if pods.items:
            pod_name = pods.items[0].metadata.name
            logs = core_client.read_namespaced_pod_log(name=pod_name,
                                                       namespace=namespace)
        return logs
    except client.ApiException as e:
        logger.error(f"Error getting job logs: {e}")
        raise


def get_container_status_obj(pod):
    container_status = None
    if pod.status.container_statuses:
        container_status = pod.status.container_statuses[0]
    elif pod.status.init_container_statuses:
        initContainerStatus = pod.status.init_container_statuses[0]
        if not initContainerStatus.state.terminated:
            logger.info("Using init container status")
            container_status = initContainerStatus
        else:
            logger.info("Using container status")
    return container_status


def get_service_endpoint(namespace, service_name):
    endpoint = None
    try:
        # Get the service information
        service = get_core_v1_client().read_namespaced_service(
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
