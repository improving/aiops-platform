"""Fake Kubernetes pods, listings, events and a CoreV1 client for the
pod inspection and operations tests."""

from types import SimpleNamespace
from unittest import mock

from kubernetes.client.exceptions import ApiException


def fake_pod(name, containers=("ollama",)):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, uid=f"uid-{name}"),
        spec=SimpleNamespace(
            containers=[SimpleNamespace(name=c) for c in containers]
        ),
    )


def fake_listing(*items):
    return SimpleNamespace(items=list(items))


def fake_core(pods, logs=None):
    """A CoreV1 mock listing ``pods``; ``logs`` maps
    ``(pod, container, previous)`` to the log text, anything else 400s.

    ``read_namespaced_pod_log`` answers the way the real client does:
    with ``_preload_content=False`` the caller gets the raw response and
    has to decode ``.data`` itself, which is what pod_inspection does.
    """
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(*pods)
    logs = logs or {}

    def read_log(
        name,
        namespace,
        container,
        tail_lines,
        previous,
        _preload_content=True,
    ):
        key = (name, container, previous)
        if key not in logs:
            raise ApiException(status=400, reason="no previous container")
        text = logs[key]
        if _preload_content:
            return text
        return SimpleNamespace(data=text.encode())

    core.read_namespaced_pod_log.side_effect = read_log
    return core


def fake_event(
    kind,
    name,
    reason,
    at,
    message="m",
    type_="Normal",
    count=None,
    first_at=None,
):
    return SimpleNamespace(
        involved_object=SimpleNamespace(kind=kind, name=name),
        reason=reason,
        message=message,
        type=type_,
        last_timestamp=at,
        event_time=None,
        first_timestamp=first_at,
        count=count,
    )
