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
    ``(pod, container, previous)`` to the log text, anything else 400s."""
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(*pods)
    logs = logs or {}

    def read_log(name, namespace, container, tail_lines, previous):
        key = (name, container, previous)
        if key not in logs:
            raise ApiException(status=400, reason="no previous container")
        return logs[key]

    core.read_namespaced_pod_log.side_effect = read_log
    return core


def fake_event(kind, name, reason, at, message="m", type_="Normal"):
    return SimpleNamespace(
        involved_object=SimpleNamespace(kind=kind, name=name),
        reason=reason,
        message=message,
        type=type_,
        last_timestamp=at,
        event_time=None,
        first_timestamp=None,
    )
