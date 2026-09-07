"""Logs and events of the pods behind one instance (spec 6.2).

One implementation for the three instance routers. Every function takes
the namespace and the pod label selector, plus optional API clients so
tests can pass mocks; the defaults come from utils/kubernetes_utils.py.
"""

from kubernetes.client.exceptions import ApiException

from utils.kubernetes_utils import get_apps_v1_client, get_core_v1_client

# `tail` is clamped to this many lines; the UI offers 200, 1000 and 5000.
MAX_TAIL = 5000
# Newest events returned per instance.
MAX_EVENTS = 100


def pod_logs(
    namespace: str,
    labels: str,
    tail: int = 200,
    previous: bool = False,
    container: str | None = None,
    *,
    core_v1=None,
) -> dict:
    """``{"pods": [{"name", "containers": [{"name", "log"}]}]}`` for the
    pods matching ``labels``; ``container`` keeps only that container."""
    core_v1 = core_v1 or get_core_v1_client()
    tail = max(1, min(int(tail), MAX_TAIL))
    pods = core_v1.list_namespaced_pod(
        namespace=namespace, label_selector=labels
    )
    result = []
    for pod in pods.items:
        names = [c.name for c in (pod.spec.containers or [])]
        if container:
            names = [name for name in names if name == container]
        containers = [
            {
                "name": name,
                "log": _read_log(
                    core_v1, namespace, pod.metadata.name, name, tail, previous
                ),
            }
            for name in names
        ]
        result.append({"name": pod.metadata.name, "containers": containers})
    return {"pods": result}


def _as_text(value) -> str:
    """The log body as text, whatever shape the client handed back.

    ``read_namespaced_pod_log`` is declared to return ``str``, so the
    client passes the response body through ``str()``. On a body it did
    not decode that yields the *repr* of the bytes: the log arrives as
    ``b'[GIN] ...\\n...'`` with every newline as the two characters
    backslash and n, and every non-ASCII byte as ``\\xc2\\xb5``. Reading
    the response raw (``_preload_content=False``) and decoding it here is
    the only way to get the real text; ``value`` is then the raw response
    object, but the test fixtures pass a plain string.
    """
    data = getattr(value, "data", value)
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def _read_log(core_v1, namespace, pod, container, tail, previous) -> str:
    try:
        response = core_v1.read_namespaced_pod_log(
            name=pod,
            namespace=namespace,
            container=container,
            tail_lines=tail,
            previous=previous,
            _preload_content=False,
        )
    except ApiException as e:
        # 400: the container has not started yet, or has no previous run
        # (previous=True on a first start). 404: the pod went away between
        # the list and the read. Both are "no log", not an error.
        if e.status in (400, 404):
            return ""
        raise
    return _as_text(response)


def pod_events(
    namespace: str, labels: str, *, core_v1=None, apps_v1=None
) -> list[dict]:
    """The events of the pods, Deployments and StatefulSets matching
    ``labels``, newest first, at most MAX_EVENTS."""
    core_v1 = core_v1 or get_core_v1_client()
    apps_v1 = apps_v1 or get_apps_v1_client()
    objects: set[tuple[str, str]] = set()
    for pod in core_v1.list_namespaced_pod(
        namespace=namespace, label_selector=labels
    ).items:
        objects.add(("Pod", pod.metadata.name))
    for deployment in apps_v1.list_namespaced_deployment(
        namespace=namespace, label_selector=labels
    ).items:
        objects.add(("Deployment", deployment.metadata.name))
    for stateful_set in apps_v1.list_namespaced_stateful_set(
        namespace=namespace, label_selector=labels
    ).items:
        objects.add(("StatefulSet", stateful_set.metadata.name))
    if not objects:
        return []

    events = []
    for event in core_v1.list_namespaced_event(namespace=namespace).items:
        involved = event.involved_object
        if involved is None or (involved.kind, involved.name) not in objects:
            continue
        at = event.last_timestamp or event.event_time or event.first_timestamp
        events.append(
            {
                "at": at.isoformat() if at else None,
                "type": event.type or "",
                "reason": event.reason or "",
                "message": event.message or "",
                "object": f"{involved.kind}/{involved.name}",
            }
        )
    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events[:MAX_EVENTS]
