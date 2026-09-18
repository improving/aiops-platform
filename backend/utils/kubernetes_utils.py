import os
from datetime import UTC, datetime
from typing import NamedTuple

from fastapi import HTTPException
from kubernetes import client, config
from urllib3.util.retry import Retry

from logger import setup_logger

# Initialize the logger
logger = setup_logger(__name__)

DEFAULT_NAMESPACE = "ai-stack"


def get_default_namespace() -> str:
    """Namespace for managed releases; AIOPS_NAMESPACE overrides it."""
    return os.environ.get("AIOPS_NAMESPACE") or DEFAULT_NAMESPACE


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
                detail="Failed to load Kubernetes configuration",
            )


def get_core_v1_client():
    api_client = get_kubernetes_api_client()
    return client.CoreV1Api(api_client)


def get_batch_v1_client():
    api_client = get_kubernetes_api_client()
    return client.BatchV1Api(api_client=api_client)


def get_apps_v1_client():
    api_client = get_kubernetes_api_client()
    return client.AppsV1Api(api_client=api_client)


# The annotation `kubectl rollout restart` sets; changing it rolls the pods.
RESTARTED_AT_ANNOTATION = "kubectl.kubernetes.io/restartedAt"


def restart_workload(namespace, labels, apps_v1=None) -> str:
    """Roll the Deployment (else the StatefulSet) matching ``labels`` the
    way ``kubectl rollout restart`` does. Returns ``"<Kind>/<name>"``;
    raises LookupError when nothing matches (a failed install)."""
    apps_v1 = apps_v1 or get_apps_v1_client()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        RESTARTED_AT_ANNOTATION: datetime.now(UTC).isoformat(
                            timespec="seconds"
                        )
                    }
                }
            }
        }
    }
    candidates = (
        (
            "Deployment",
            apps_v1.list_namespaced_deployment,
            apps_v1.patch_namespaced_deployment,
        ),
        (
            "StatefulSet",
            apps_v1.list_namespaced_stateful_set,
            apps_v1.patch_namespaced_stateful_set,
        ),
    )
    for kind, list_fn, patch_fn in candidates:
        items = list_fn(namespace=namespace, label_selector=labels).items
        if items:
            name = items[0].metadata.name
            patch_fn(name=name, namespace=namespace, body=body)
            logger.info("Restarted %s/%s in %s", kind, name, namespace)
            return f"{kind}/{name}"
    raise LookupError(
        f"No Deployment or StatefulSet matches {labels} in {namespace}"
    )


def get_kubernetes_api_client():
    load_kubernetes_config()
    configuration = client.Configuration.get_default_copy()
    configuration.client_side_validation = False
    # kubernetes.client.Configuration has no global timeout; requests take
    # _request_timeout per call.
    retry = Retry(
        total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504]
    )
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
            body=client.V1DeleteOptions(propagation_policy="Foreground"),
        )
        logger.info(f"Job {job_name} deleted successfully")
    except client.exceptions.ApiException as e:
        logger.exception(f"Error deleting job: {e}")


def create_config_map(namespace, config_map):
    core_v1_api = get_core_v1_client()
    try:
        core_v1_api.create_namespaced_config_map(
            namespace=namespace, body=config_map
        )
        logger.info(
            f"ConfigMap {config_map.metadata.name} created successfully"
        )
    except client.exceptions.ApiException as e:
        logger.exception(f"Error creating config map: {e}")
        raise


def delete_config_map(namespace, config_map_name):
    core_v1_api = get_core_v1_client()
    try:
        core_v1_api.delete_namespaced_config_map(
            namespace=namespace, name=config_map_name
        )
        logger.info(f"ConfigMap {config_map_name} deleted successfully")
    except client.exceptions.ApiException as e:
        logger.exception(f"Error deleting config map: {e}")
        raise


# Container reasons that mean the workload is not going to come up on its
# own (spec 6.1); the poller turns them into status Failed.
FAILURE_REASONS = frozenset(
    {
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "OOMKilled",
        "Error",
    }
)


# The phases of LaunchProgress, least advanced first: with several pods the
# least advanced one is what the instance is waiting for.
LAUNCH_SCHEDULING = "Scheduling"
LAUNCH_BLOCKED = "Blocked"
LAUNCH_PULLING = "Pulling image"
LAUNCH_RESTARTING = "Restarting"
LAUNCH_STARTING = "Starting"
LAUNCH_TERMINATING = "Terminating"
_LAUNCH_ORDER = (
    LAUNCH_SCHEDULING,
    LAUNCH_BLOCKED,
    LAUNCH_PULLING,
    LAUNCH_RESTARTING,
    LAUNCH_STARTING,
)
# Waiting reasons of a container that is on its way, not in trouble.
_CREATING_REASONS = frozenset({"ContainerCreating", "PodInitializing"})
# A pod in one of these phases stays in the listing (an evicted pod, a
# finished job) and is not on its way up.
_FINISHED_PHASES = frozenset({"Succeeded", "Failed"})


class LaunchProgress(NamedTuple):
    """What an instance that is not ready yet is doing, for a person: a
    phase from the closed set above, one sentence, since when (ISO 8601),
    whether only a person can move it on, and the counts that tell a slow
    start from a loop. Derived on every read from the pod listing; never
    stored, and never a ``status``."""

    phase: str
    message: str
    since: str | None
    # An image pull and a model load need time; a pod no node can take, a
    # container that cannot be created and a restart loop need a person.
    needs_attention: bool = False
    restart_count: int = 0
    replicas_total: int = 1
    # Of a model download (utils/model_cache.py); None when not known.
    downloaded_bytes: int | None = None
    total_bytes: int | None = None


class PodStatus(NamedTuple):
    """What the pods behind an instance report. The first two fields are
    the (ready, status) pair this function always returned; ``failure``
    is the first container reason from FAILURE_REASONS with its message;
    ``launch`` says what a not-ready instance is waiting for, and is None
    once it is ready or has failed (``failure`` covers that)."""

    ready: bool
    status: str
    failure: tuple[str, str] | None = None
    launch: LaunchProgress | None = None


def _iso(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _pod_is_ready(pod) -> bool:
    # A pod being deleted (stop, scale, a Recreate restart) may still answer
    # Ready while it drains; it is not the instance's readiness.
    statuses = getattr(pod.status, "container_statuses", None)
    return (
        pod.status.phase == "Running"
        and not getattr(pod.metadata, "deletion_timestamp", None)
        and bool(statuses)
        and all(c.ready for c in statuses)
    )


def _unscheduled(pod, since) -> LaunchProgress:
    for condition in getattr(pod.status, "conditions", None) or []:
        if condition.type == "PodScheduled" and condition.status == "False":
            reason = condition.reason or "Unschedulable"
            message = condition.message or ""
            return LaunchProgress(
                phase=LAUNCH_SCHEDULING,
                message=f"{reason}: {message}" if message else reason,
                since=since,
                needs_attention=True,
            )
    return LaunchProgress(
        phase=LAUNCH_SCHEDULING, message="Waiting for a node", since=since
    )


def _restarting(statuses, restarts: int, since) -> LaunchProgress:
    last = next(
        (
            c.last_state.terminated
            for c in statuses
            if getattr(c, "last_state", None)
            and getattr(c.last_state, "terminated", None)
        ),
        None,
    )
    times = "time" if restarts == 1 else "times"
    message = f"Restarted {restarts} {times}"
    if last is not None:
        code = getattr(last, "exit_code", None)
        message += f", last exit: {last.reason or 'unknown'}" + (
            f" (code {code})" if code is not None else ""
        )
    message += '. See the Logs tab with "previous" for the reason'
    return LaunchProgress(
        phase=LAUNCH_RESTARTING,
        message=message,
        since=since,
        needs_attention=True,
        restart_count=restarts,
    )


def _pod_launch(pod) -> LaunchProgress:
    """What one pod that is not ready is waiting for. The rules, in order:
    not scheduled, restarting, a container being created, a container that
    cannot be created, and else a container that runs and is not ready."""
    created = _iso(getattr(pod.metadata, "creation_timestamp", None))
    statuses = list(getattr(pod.status, "container_statuses", None) or [])
    if not statuses:
        return _unscheduled(pod, created)

    restarts = sum(getattr(c, "restart_count", 0) or 0 for c in statuses)
    if restarts:
        return _restarting(statuses, restarts, created)

    init_statuses = list(
        getattr(pod.status, "init_container_statuses", None) or []
    )
    for cs in init_statuses + statuses:
        waiting = getattr(cs.state, "waiting", None) if cs.state else None
        if not waiting or not waiting.reason:
            continue
        if waiting.reason in _CREATING_REASONS:
            return LaunchProgress(
                phase=LAUNCH_PULLING,
                message="Pulling the image and creating the container",
                since=created,
            )
        # CreateContainerConfigError (a missing Secret), InvalidImageName
        # and the like: the container does not run.
        detail = f": {waiting.message}" if waiting.message else ""
        return LaunchProgress(
            phase=LAUNCH_BLOCKED,
            message=f"{waiting.reason}{detail}",
            since=created,
            needs_attention=True,
        )

    started = next(
        (
            cs.state.running.started_at
            for cs in statuses
            if cs.state and getattr(cs.state, "running", None)
        ),
        None,
    )
    return LaunchProgress(
        phase=LAUNCH_STARTING,
        message=(
            "The container runs and is not ready yet: a model server "
            "downloads and loads its model in this step"
        ),
        since=_iso(started) or created,
    )


def _launch_progress(pods, failure) -> LaunchProgress | None:
    """See LaunchProgress. None without pods, when a pod serves, or when
    ``failure`` is set: last_error and the error banner own that case."""
    pods = [p for p in pods if p.status.phase not in _FINISHED_PHASES]
    if not pods or failure is not None:
        return None
    if any(_pod_is_ready(pod) for pod in pods):
        return None
    live = [
        pod
        for pod in pods
        if not getattr(pod.metadata, "deletion_timestamp", None)
    ]
    if not live:
        return LaunchProgress(
            phase=LAUNCH_TERMINATING,
            message="The pods are shutting down",
            since=None,
            replicas_total=len(pods),
        )
    least_advanced = min(
        (_pod_launch(pod) for pod in live),
        key=lambda launch: _LAUNCH_ORDER.index(launch.phase),
    )
    return least_advanced._replace(replicas_total=len(live))


def _first_failure(pods) -> tuple[str, str] | None:
    """(reason, message) of the first container in a failure state.

    A pod being deleted (stop, scale, a Recreate restart) reports
    terminated.reason "Error" for its SIGTERM exit; it is skipped, or
    Stopped and Pending would flicker to Failed for a few seconds."""
    for pod in pods:
        if getattr(pod.metadata, "deletion_timestamp", None):
            continue
        statuses = list(pod.status.init_container_statuses or []) + list(
            pod.status.container_statuses or []
        )
        for cs in statuses:
            state = cs.state
            if state is None:
                continue
            if state.waiting and state.waiting.reason in FAILURE_REASONS:
                return state.waiting.reason, state.waiting.message or ""
            if state.terminated and state.terminated.reason in FAILURE_REASONS:
                return state.terminated.reason, state.terminated.message or ""
    return None


def get_pod_status_and_readiness(
    namespace, pod_labels, core_v1=None
) -> PodStatus:
    """Readiness, the first container's state as a word, and the first
    failure reason with its message, for the pods matching pod_labels."""
    try:
        core_v1 = core_v1 or get_core_v1_client()
        pods = core_v1.list_namespaced_pod(
            namespace=namespace, label_selector=pod_labels
        )
    except client.exceptions.ApiException as e:
        logger.exception(f"Error checking pod status and readiness: {e}")
        return PodStatus(False, "Unknown")

    instance_ready = any(_pod_is_ready(pod) for pod in pods.items)

    instance_status = "Unknown"
    if pods.items:
        pod = pods.items[0]
        container_status = get_container_status_obj(pod)
        if container_status:
            logger.debug(
                f"Pod Name: {pod.metadata.name}, Status: {container_status}"
            )
            state = container_status.state
            if not container_status.started and state.waiting:
                instance_status = state.waiting.reason
            elif not container_status.started and state.terminated:
                instance_status = "Terminated"
            elif container_status.started or (
                state.running and state.running.started_at
            ):
                instance_status = "Running"
    failure = _first_failure(pods.items)
    return PodStatus(
        ready=instance_ready,
        status=instance_status,
        failure=failure,
        launch=_launch_progress(pods.items, failure),
    )


async def get_job_status(job_name, namespace):
    job_client = get_batch_v1_client()
    job_status = "Unknown"
    try:
        job = job_client.read_namespaced_job_status(
            name=job_name, namespace=namespace
        )
        if job:
            job_status = interpret_job_status(job.status)

        return job_status
    except client.ApiException as e:
        logger.error(f"Error getting job status: {e}")


def interpret_job_status(job_status):
    status = "Running"

    if job_status.conditions:
        for condition in job_status.conditions:
            if condition.type == "Complete":
                status = (
                    "Completed" if condition.status == "True" else "Failed"
                )
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
            namespace=namespace, label_selector=f"job-name={job_name}"
        )
        if pods.items:
            pod_name = pods.items[0].metadata.name
            logs = core_client.read_namespaced_pod_log(
                name=pod_name, namespace=namespace
            )
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


def _get_service_host(service):
    """Return the host to reach the service on, or None when unknown.

    A LoadBalancer service gets its ingress IP, else its ingress hostname.
    Without an ingress (no LoadBalancer provider, as on kind) the cluster IP
    is used. Headless services report the string "None" as cluster IP.
    """
    if service.spec.type == "LoadBalancer":
        ingress = service.status.load_balancer.ingress or []
        for entry in ingress:
            host = entry.ip or entry.hostname
            if host:
                return host

    cluster_ip = service.spec.cluster_ip
    if cluster_ip and cluster_ip != "None":
        return cluster_ip
    return None


def get_service_endpoint(namespace, service_name):
    endpoint = None
    try:
        # Get the service information
        service = get_core_v1_client().read_namespaced_service(
            name=service_name, namespace=namespace
        )

        host = _get_service_host(service)
        port = service.spec.ports[0].port if service.spec.ports else None

        if host and port:
            endpoint = f"http://{host}:{port}"
        else:
            # Return None so the scheduler polls again instead of
            # storing an endpoint such as http://None:6333.
            logger.warning(
                f"Warning: Could not determine IP or port for service {service_name}"
            )
    except client.exceptions.ApiException as e:
        if e.status == 404:
            # The scheduler polls until the Helm release creates the service.
            logger.info(
                "Service %s/%s does not exist yet", namespace, service_name
            )
        else:
            logger.exception(f"Error getting service information: {e}")

    return endpoint
