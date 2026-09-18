"""Unit tests for utils/pod_inspection.py with mocked Kubernetes clients."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

from kubernetes.client.exceptions import ApiException

from testing.pods import fake_core, fake_event, fake_listing, fake_pod
from utils.kubernetes_utils import (
    RESTARTED_AT_ANNOTATION,
    PodStatus,
    get_pod_status_and_readiness,
    restart_workload,
)
from utils.pod_inspection import MAX_EVENTS, pod_events, pod_logs

LABELS = (
    "app.kubernetes.io/instance=ollama-abcdef12,app.kubernetes.io/name=ollama"
)


def test_pod_logs_returns_every_container_of_every_pod():
    core = fake_core(
        [fake_pod("a", ("main", "side")), fake_pod("b")],
        logs={
            ("a", "main", False): "hello",
            ("a", "side", False): "side",
            ("b", "ollama", False): "b-log",
        },
    )
    result = pod_logs("ai-stack", LABELS, tail=50, core_v1=core)
    assert result == {
        "pods": [
            {
                "name": "a",
                "containers": [
                    {"name": "main", "log": "hello"},
                    {"name": "side", "log": "side"},
                ],
            },
            {"name": "b", "containers": [{"name": "ollama", "log": "b-log"}]},
        ]
    }
    core.list_namespaced_pod.assert_called_once_with(
        namespace="ai-stack", label_selector=LABELS
    )
    first = core.read_namespaced_pod_log.call_args_list[0].kwargs
    assert first == {
        "name": "a",
        "namespace": "ai-stack",
        "container": "main",
        "tail_lines": 50,
        "previous": False,
        # Raw, so the body is decoded here rather than by str().
        "_preload_content": False,
    }


def test_pod_logs_filters_by_container_and_clamps_tail():
    core = fake_core(
        [fake_pod("a", ("main", "side"))], logs={("a", "side", False): "s"}
    )
    result = pod_logs(
        "ai-stack", LABELS, tail=99999, container="side", core_v1=core
    )
    assert result["pods"][0]["containers"] == [{"name": "side", "log": "s"}]
    assert core.read_namespaced_pod_log.call_args.kwargs["tail_lines"] == 5000
    assert (
        pod_logs("ai-stack", LABELS, tail=0, core_v1=fake_core([]))["pods"]
        == []
    )


def test_pod_logs_previous_without_a_previous_run_is_empty():
    core = fake_core([fake_pod("a")], logs={("a", "ollama", False): "current"})
    result = pod_logs("ai-stack", LABELS, previous=True, core_v1=core)
    assert result["pods"][0]["containers"] == [{"name": "ollama", "log": ""}]
    assert core.read_namespaced_pod_log.call_args.kwargs["previous"] is True


def test_pod_events_keeps_pod_and_workload_events_newest_first():
    t1 = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 6, 10, 5, tzinfo=UTC)
    core = fake_core([fake_pod("a")])
    core.list_namespaced_event.return_value = fake_listing(
        fake_event("Pod", "a", "Pulled", t1),
        fake_event("Deployment", "ollama-abcdef12", "ScalingReplicaSet", t2),
        fake_event("Pod", "unrelated", "Killing", t2),
        fake_event("Pod", "a", "BackOff", None, type_="Warning"),
    )
    apps = mock.Mock()
    apps.list_namespaced_deployment.return_value = fake_listing(
        SimpleNamespace(metadata=SimpleNamespace(name="ollama-abcdef12"))
    )
    apps.list_namespaced_stateful_set.return_value = fake_listing()

    events = pod_events("ai-stack", LABELS, core_v1=core, apps_v1=apps)

    assert [e["reason"] for e in events] == [
        "ScalingReplicaSet",
        "Pulled",
        "BackOff",
    ]
    assert events[0] == {
        "at": t2.isoformat(),
        "type": "Normal",
        "reason": "ScalingReplicaSet",
        "message": "m",
        "object": "Deployment/ollama-abcdef12",
    }
    assert events[2]["at"] is None
    apps.list_namespaced_deployment.assert_called_once_with(
        namespace="ai-stack", label_selector=LABELS
    )
    core.list_namespaced_event.assert_called_once_with(namespace="ai-stack")


def test_pod_events_is_capped_and_empty_without_objects():
    core = fake_core([fake_pod("a")])
    core.list_namespaced_event.return_value = fake_listing(
        *[
            fake_event("Pod", "a", f"r{i}", datetime(2026, 1, 1, tzinfo=UTC))
            for i in range(MAX_EVENTS + 20)
        ]
    )
    apps = mock.Mock()
    apps.list_namespaced_deployment.return_value = fake_listing()
    apps.list_namespaced_stateful_set.return_value = fake_listing()
    assert len(pod_events("ai-stack", LABELS, core_v1=core, apps_v1=apps)) == (
        MAX_EVENTS
    )

    empty = fake_core([])
    assert pod_events("ai-stack", LABELS, core_v1=empty, apps_v1=apps) == []
    empty.list_namespaced_event.assert_not_called()


def _status_pod(phase, statuses, init_statuses=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(name="p"),
        status=SimpleNamespace(
            phase=phase,
            container_statuses=statuses,
            init_container_statuses=init_statuses,
        ),
    )


def _container(ready, started, waiting=None, terminated=None, running=None):
    state = SimpleNamespace(
        waiting=waiting, terminated=terminated, running=running
    )
    return SimpleNamespace(
        ready=ready, started=started, state=state, last_state=None
    )


def _waiting(reason, message="msg"):
    return SimpleNamespace(reason=reason, message=message)


def test_get_pod_status_and_readiness_ready():
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(
        _status_pod(
            "Running",
            [_container(True, True, running=SimpleNamespace(started_at="t"))],
        )
    )
    assert get_pod_status_and_readiness(
        "ns", LABELS, core_v1=core
    ) == PodStatus(True, "Running", None)


def test_get_pod_status_and_readiness_reports_crashloop_with_message():
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(
        _status_pod(
            "Running",
            [
                _container(
                    False,
                    False,
                    waiting=_waiting("CrashLoopBackOff", "back-off 5m"),
                )
            ],
        )
    )
    assert get_pod_status_and_readiness(
        "ns", LABELS, core_v1=core
    ) == PodStatus(
        False, "CrashLoopBackOff", ("CrashLoopBackOff", "back-off 5m")
    )


def test_get_pod_status_and_readiness_reports_oomkilled_from_terminated_state():
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(
        _status_pod(
            "Running",
            [
                _container(
                    False,
                    False,
                    terminated=SimpleNamespace(
                        reason="OOMKilled", message=None
                    ),
                )
            ],
        )
    )
    pods = get_pod_status_and_readiness("ns", LABELS, core_v1=core)
    assert pods.status == "Terminated"
    assert pods.failure == ("OOMKilled", "")


def test_get_pod_status_and_readiness_container_creating_is_not_a_failure():
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(
        _status_pod(
            "Pending",
            [_container(False, False, waiting=_waiting("ContainerCreating"))],
        )
    )
    pods = get_pod_status_and_readiness("ns", LABELS, core_v1=core)
    assert pods[:3] == (False, "ContainerCreating", None)
    # Not a failure; the launch progress names it (see below).
    assert pods.launch.phase == "Pulling image"


def test_get_pod_status_and_readiness_skips_a_terminating_pod():
    """A pod being deleted exits with terminated.reason "Error" (SIGTERM);
    that is not a failure of the instance."""
    core = mock.Mock()
    exiting = _status_pod(
        "Running",
        [
            _container(
                False,
                False,
                terminated=SimpleNamespace(reason="Error", message="143"),
            )
        ],
    )
    exiting.metadata = SimpleNamespace(
        name="p", deletion_timestamp="2026-09-06"
    )
    core.list_namespaced_pod.return_value = fake_listing(exiting)
    assert (
        get_pod_status_and_readiness("ns", LABELS, core_v1=core).failure
        is None
    )

    # Right after a stop the old pod is still Ready while it drains; it
    # must not count as readiness either, or Stopped would flip to Running.
    draining = _status_pod(
        "Running",
        [_container(True, True, running=SimpleNamespace(started_at="t"))],
    )
    draining.metadata = SimpleNamespace(
        name="q", deletion_timestamp="2026-09-06"
    )
    core.list_namespaced_pod.return_value = fake_listing(draining)
    assert (
        get_pod_status_and_readiness("ns", LABELS, core_v1=core).ready is False
    )


def test_get_pod_status_and_readiness_without_pods_or_with_an_api_error():
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing()
    assert get_pod_status_and_readiness(
        "ns", LABELS, core_v1=core
    ) == PodStatus(False, "Unknown", None)
    core.list_namespaced_pod.side_effect = ApiException(status=500)
    assert get_pod_status_and_readiness(
        "ns", LABELS, core_v1=core
    ) == PodStatus(False, "Unknown", None)


def _workload(name):
    return SimpleNamespace(metadata=SimpleNamespace(name=name))


def test_restart_workload_patches_the_deployment():
    apps = mock.Mock()
    apps.list_namespaced_deployment.return_value = fake_listing(
        _workload("ollama-abcdef12")
    )
    assert (
        restart_workload("ai-stack", LABELS, apps_v1=apps)
        == "Deployment/ollama-abcdef12"
    )
    apps.list_namespaced_deployment.assert_called_once_with(
        namespace="ai-stack", label_selector=LABELS
    )
    call = apps.patch_namespaced_deployment.call_args.kwargs
    assert (call["name"], call["namespace"]) == ("ollama-abcdef12", "ai-stack")
    annotations = call["body"]["spec"]["template"]["metadata"]["annotations"]
    assert annotations[RESTARTED_AT_ANNOTATION].startswith("20")
    apps.patch_namespaced_stateful_set.assert_not_called()


def test_restart_workload_falls_back_to_the_stateful_set():
    apps = mock.Mock()
    apps.list_namespaced_deployment.return_value = fake_listing()
    apps.list_namespaced_stateful_set.return_value = fake_listing(
        _workload("qdrant-abcdef12")
    )
    assert (
        restart_workload("ai-stack", LABELS, apps_v1=apps)
        == "StatefulSet/qdrant-abcdef12"
    )
    apps.patch_namespaced_stateful_set.assert_called_once()


def test_restart_workload_without_a_workload_raises():
    apps = mock.Mock()
    apps.list_namespaced_deployment.return_value = fake_listing()
    apps.list_namespaced_stateful_set.return_value = fake_listing()
    import pytest

    with pytest.raises(LookupError):
        restart_workload("ai-stack", LABELS, apps_v1=apps)


def test_pod_logs_decodes_the_raw_response_body():
    """Without _preload_content=False and the decode, the client passes
    the undecoded body through str(): the UI then shows b'...' with every
    newline as the two characters backslash and n."""
    core = fake_core(
        [fake_pod("a")],
        logs={("a", "ollama", False): "200 | 121.749\u00b5s\nready\n"},
    )

    log = pod_logs("ai-stack", LABELS, core_v1=core)["pods"][0]["containers"][
        0
    ]["log"]

    assert log == "200 | 121.749\u00b5s\nready\n"
    assert not log.startswith("b'")
    assert log.count("\n") == 2
    assert "\\n" not in log
    kwargs = core.read_namespaced_pod_log.call_args.kwargs
    assert kwargs["_preload_content"] is False


def test_pod_logs_replaces_bytes_that_are_not_utf_8():
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(fake_pod("a"))
    core.read_namespaced_pod_log.return_value = SimpleNamespace(
        data=b"first\n\xff\xfe rest\n"
    )

    log = pod_logs("ai-stack", LABELS, core_v1=core)["pods"][0]["containers"][
        0
    ]["log"]

    assert log.startswith("first\n")
    assert log.endswith(" rest\n")


# --- launch progress ------------------------------------------------------------
#
# What a user sees while an instance is Pending. Measured on the lab's first
# GPU launch: 5.6 minutes of image pull, then minutes of weight download and
# load, then a restart loop, all behind the one word "Pending".

CREATED = datetime(2026, 9, 18, 11, 39, 42, tzinfo=UTC)
STARTED = datetime(2026, 9, 18, 11, 45, 20, tzinfo=UTC)


def _launch_pod(
    statuses=None,
    *,
    phase="Pending",
    conditions=None,
    deleting=False,
    init_statuses=None,
):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name="p",
            creation_timestamp=CREATED,
            deletion_timestamp=CREATED if deleting else None,
        ),
        status=SimpleNamespace(
            phase=phase,
            conditions=conditions,
            container_statuses=statuses,
            init_container_statuses=init_statuses,
        ),
    )


def _launch_container(
    *, ready=False, waiting=None, running=None, restarts=0, last=None
):
    return SimpleNamespace(
        ready=ready,
        started=bool(running),
        restart_count=restarts,
        state=SimpleNamespace(
            waiting=waiting, terminated=None, running=running
        ),
        last_state=SimpleNamespace(terminated=last) if last else None,
    )


def _launch(*pods):
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(*pods)
    return get_pod_status_and_readiness("ns", LABELS, core_v1=core).launch


def test_launch_says_why_a_pod_is_not_scheduled():
    # The worst case before: a GPU request nothing can satisfy stayed
    # "Pending" forever with no reason anywhere.
    unschedulable = SimpleNamespace(
        type="PodScheduled",
        status="False",
        reason="Unschedulable",
        message="0/1 nodes are available: 1 Insufficient nvidia.com/gpu.",
    )
    launch = _launch(_launch_pod(None, conditions=[unschedulable]))
    assert launch.phase == "Scheduling"
    assert launch.message == (
        "Unschedulable: 0/1 nodes are available: "
        "1 Insufficient nvidia.com/gpu."
    )
    assert launch.since == CREATED.isoformat()
    assert launch.replicas_total == 1
    # No node can take the pod: only a person can change that.
    assert launch.needs_attention is True


def test_launch_waits_for_a_node_before_any_condition_exists():
    launch = _launch(_launch_pod(None))
    assert launch.phase == "Scheduling"
    assert launch.message == "Waiting for a node"
    assert launch.needs_attention is False


def test_launch_names_the_image_pull():
    launch = _launch(
        _launch_pod(
            [_launch_container(waiting=_waiting("ContainerCreating", None))]
        )
    )
    assert launch.phase == "Pulling image"
    assert launch.message == "Pulling the image and creating the container"
    assert launch.since == CREATED.isoformat()
    assert launch.needs_attention is False


def test_launch_counts_an_init_container_as_the_image_phase():
    launch = _launch(
        _launch_pod(
            [_launch_container(waiting=_waiting("PodInitializing", None))],
            init_statuses=[
                _launch_container(running=SimpleNamespace(started_at=STARTED))
            ],
        )
    )
    assert launch.phase == "Pulling image"


def test_launch_is_starting_once_the_container_runs():
    launch = _launch(
        _launch_pod(
            [_launch_container(running=SimpleNamespace(started_at=STARTED))],
            phase="Running",
        )
    )
    assert launch.phase == "Starting"
    assert launch.message == (
        "The container runs and is not ready yet: "
        "a model server downloads and loads its model in this step"
    )
    assert launch.since == STARTED.isoformat()
    assert launch.restart_count == 0


def test_launch_reports_restarts_with_the_last_exit():
    # A liveness kill is exit 137 with reason "Error"; below the
    # CrashLoopBackOff threshold nothing showed it.
    launch = _launch(
        _launch_pod(
            [
                _launch_container(
                    running=SimpleNamespace(started_at=STARTED),
                    restarts=3,
                    last=SimpleNamespace(reason="Error", exit_code=137),
                )
            ],
            phase="Running",
        )
    )
    assert launch.phase == "Restarting"
    assert launch.restart_count == 3
    assert launch.needs_attention is True
    assert launch.message == (
        "Restarted 3 times, last exit: Error (code 137). "
        'See the Logs tab with "previous" for the reason'
    )


def test_launch_is_terminating_when_every_pod_is_going():
    launch = _launch(
        _launch_pod(
            [
                _launch_container(
                    ready=True, running=SimpleNamespace(started_at=STARTED)
                )
            ],
            phase="Running",
            deleting=True,
        )
    )
    assert launch.phase == "Terminating"


def test_launch_is_none_when_ready_failed_or_without_pods():
    ready = _launch_pod(
        [
            _launch_container(
                ready=True, running=SimpleNamespace(started_at=STARTED)
            )
        ],
        phase="Running",
    )
    assert _launch(ready) is None
    # A failure has its own surface: last_error and the error banner.
    crashing = _launch_pod(
        [_launch_container(waiting=_waiting("CrashLoopBackOff"), restarts=6)]
    )
    assert _launch(crashing) is None
    assert _launch() is None


def test_launch_takes_the_least_advanced_pod_and_counts_replicas():
    started = _launch_pod(
        [
            _launch_container(
                ready=True, running=SimpleNamespace(started_at=STARTED)
            )
        ],
        phase="Running",
    )
    pulling = _launch_pod(
        [_launch_container(waiting=_waiting("ContainerCreating", None))]
    )
    core = mock.Mock()
    core.list_namespaced_pod.return_value = fake_listing(started, pulling)
    pods = get_pod_status_and_readiness("ns", LABELS, core_v1=core)
    # One replica serves, so the instance is ready and nothing is "launching".
    assert pods.ready is True
    assert pods.launch is None

    not_ready = _launch_pod(
        [_launch_container(running=SimpleNamespace(started_at=STARTED))],
        phase="Running",
    )
    launch = _launch(not_ready, pulling)
    assert launch.phase == "Pulling image"
    assert launch.replicas_total == 2


def test_launch_ignores_an_evicted_pod_next_to_its_replacement():
    # A Failed or Succeeded pod stays in the listing. It is not on its way
    # up, and as the least advanced pod it would hide the one that is.
    evicted = _launch_pod(None, phase="Failed")
    pulling = _launch_pod(
        [_launch_container(waiting=_waiting("ContainerCreating", None))]
    )
    launch = _launch(evicted, pulling)
    assert launch.phase == "Pulling image"
    assert launch.replicas_total == 1
    assert _launch(evicted) is None


def test_launch_names_a_container_that_cannot_be_created():
    # Not "the container runs": it does not, and only a person can fix a
    # missing Secret or a bad image name.
    launch = _launch(
        _launch_pod(
            [
                _launch_container(
                    waiting=_waiting(
                        "CreateContainerConfigError",
                        'secret "hf-api-token" not found',
                    )
                )
            ]
        )
    )
    assert launch.phase == "Blocked"
    assert launch.message == (
        'CreateContainerConfigError: secret "hf-api-token" not found'
    )
    assert launch.needs_attention is True
