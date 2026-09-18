"""GET /v1alpha1/hosts: what a node offers and what is already asked of it,
which the launch form shows next to its CPU, memory and GPU inputs."""

from types import SimpleNamespace

from api.hosts import get_hosts

USER = SimpleNamespace(id="u", org_id="o")

GPU_LABELS = {
    "kubernetes.io/hostname": "gpu-node",
    "feature.node.kubernetes.io/cpu-model.vendor_id": "Intel",
    "nvidia.com/cuda.driver-version.full": "595.71.05",
    "nvidia.com/gpu.count": "1",
    "nvidia.com/gpu.memory": "24564",
    "nvidia.com/gpu.product": "NVIDIA-GeForce-RTX-4090",
}


def _node(name, labels, allocatable, ready=True):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels=labels),
        status=SimpleNamespace(
            conditions=[
                SimpleNamespace(
                    type="Ready", status="True" if ready else "False"
                )
            ],
            addresses=[SimpleNamespace(type="InternalIP", address="10.0.0.1")],
            allocatable=allocatable,
        ),
    )


def _pod(node_name, phase, *requests):
    return SimpleNamespace(
        spec=SimpleNamespace(
            node_name=node_name,
            containers=[
                SimpleNamespace(resources=SimpleNamespace(requests=r))
                for r in requests
            ],
        ),
        status=SimpleNamespace(phase=phase, host_ip="10.0.0.1"),
    )


def _core(nodes, pods):
    core = SimpleNamespace()
    core.list_node = lambda: SimpleNamespace(items=nodes)
    core.list_pod_for_all_namespaces = lambda: SimpleNamespace(items=pods)
    return core


def _hosts(nodes, pods):
    return get_hosts(includeNotReady=False, v1=_core(nodes, pods), user=USER)


def test_a_host_reports_what_it_offers_and_what_is_requested():
    node = _node(
        "gpu-node",
        GPU_LABELS,
        {"cpu": "32", "memory": "131072Mi", "nvidia.com/gpu": "1"},
    )
    pods = [
        _pod(
            "gpu-node",
            "Running",
            {"cpu": "500m", "memory": "1Gi"},
            {"cpu": "1500m", "memory": "3Gi", "nvidia.com/gpu": "1"},
        ),
        # A pod that waits for its image already holds its request.
        _pod("gpu-node", "Pending", {"cpu": "2", "memory": "4096Mi"}),
        # A pod with no requests at all (most of a small cluster).
        _pod("gpu-node", "Running", None),
    ]
    (host,) = _hosts([node], pods)
    assert host.hostname == "gpu-node"
    assert host.allocatable_cpu == 32
    assert host.allocatable_memory == 131072  # MiB, like gpu_memory
    assert host.allocatable_gpu == 1
    assert host.requested_cpu == 4
    assert host.requested_memory == 8192
    assert host.gpu_usage == 1


def test_finished_pods_and_other_nodes_do_not_count():
    node = _node("gpu-node", GPU_LABELS, {"cpu": "32", "memory": "64Gi"})
    pods = [
        # The cuda-vectoradd test pod, long done, still in the listing.
        _pod("gpu-node", "Succeeded", {"cpu": "1", "nvidia.com/gpu": "1"}),
        _pod("gpu-node", "Failed", {"cpu": "1", "memory": "1Gi"}),
        _pod("another-node", "Running", {"cpu": "8", "nvidia.com/gpu": "1"}),
        # Not scheduled yet: it holds nothing on any node.
        _pod(None, "Pending", {"cpu": "8", "nvidia.com/gpu": "1"}),
    ]
    (host,) = _hosts([node], pods)
    assert host.requested_cpu == 0
    assert host.requested_memory == 0
    assert host.gpu_usage == 0


def test_a_gpu_without_time_slicing_has_one_replica():
    # Not the GPU memory label's value ("24564 slices").
    node = _node("gpu-node", GPU_LABELS, {"cpu": "32", "memory": "64Gi"})
    (host,) = _hosts([node], [])
    assert host.gpu_replicas == 1
    assert host.gpu_memory == 24564

    sliced = _node(
        "gpu-node",
        {**GPU_LABELS, "nvidia.com/gpu.replicas": "4"},
        {"cpu": "32", "memory": "64Gi", "nvidia.com/gpu": "4"},
    )
    (host,) = _hosts([sliced], [])
    assert host.gpu_replicas == 4
    assert host.allocatable_gpu == 4


def test_a_cpu_node_without_nfd_labels_still_reports_its_size():
    # feature.node.kubernetes.io/cpu-model.cores and .memory are not labels
    # NFD publishes, so both read 0 on a real cluster; allocatable is real.
    node = _node(
        "cpu-node",
        {"kubernetes.io/hostname": "cpu-node"},
        {"cpu": "7800m", "memory": "16249128Ki"},
    )
    (host,) = _hosts([node], [])
    assert host.cpu_cores == 0
    assert host.allocatable_cpu == 7.8
    assert host.allocatable_memory == 15868
    assert host.allocatable_gpu == 0
