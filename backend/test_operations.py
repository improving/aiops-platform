"""Operations stream (#15, #16): persisted status, logs, events, actions.

Helm and Kubernetes are mocked the way test_app.py's inference_env and
vectordb_env do it; the tests share one SQLite file, so every test deletes
the rows it creates.
"""

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from core import create_app
from db.database import get_db_direct
from testing.pods import fake_core, fake_event, fake_listing, fake_pod
from testing.rows import (
    MODELS,
    NOTEBOOKS,
    add_row,
    default_org_id,
    delete_rows,
    user_id,
)
from utils.gateway import ApiKeyPolicyError
from utils.kubernetes_utils import PodStatus

CRASH = PodStatus(
    False, "CrashLoopBackOff", ("CrashLoopBackOff", "back-off 5m0s")
)
READY = PodStatus(True, "Running", None)
NO_PODS = PodStatus(False, "Unknown", None)
LABELS = (
    "app.kubernetes.io/instance=ollama-abcdef12,app.kubernetes.io/name=ollama"
)


@pytest.fixture
def inference_env(monkeypatch):
    """Mocked controller, credentials, LiteLLM and pods around the
    inference instance routes; yields (client, controller, pods) where
    pods is the mock get_pod_status_and_readiness whose return_value a test may change."""
    import api.inference_instance as ii
    import api.inference_operations as io
    import api.inference_status as ist

    controller = mock.Mock()
    controller.namespace = "ai-stack"
    controller.get_service_name.return_value = "ollama-abcdef12"
    controller.get_pod_labels.return_value = LABELS
    controller.service_url.return_value = (
        "http://ollama-abcdef12.ai-stack.svc:80"
    )
    # Both are read on every list and detail response and are typed, so a
    # bare Mock fails response validation. Ollama is the fixture's engine
    # and does not check the key itself; only vLLM does.
    controller.workload_checks_api_key = False
    controller.install = mock.AsyncMock()
    controller.uninstall = mock.AsyncMock()
    controller.upgrade = mock.AsyncMock()
    # get_controller is called from all three inference modules.
    for module in (ii, io, ist):
        monkeypatch.setattr(
            module, "get_controller", lambda *a, **k: controller
        )
    monkeypatch.setattr(ii, "store_credential", mock.Mock())
    monkeypatch.setattr(ii, "delete_credential", mock.Mock())
    monkeypatch.setattr(ii, "get_litellm_client", lambda: None)
    monkeypatch.setattr(ist, "get_service_endpoint", lambda *a, **k: None)
    pods = mock.Mock(return_value=NO_PODS)
    monkeypatch.setattr(ist, "get_pod_status_and_readiness", pods)
    return TestClient(create_app()), controller, pods


def _ollama_body(client, **extra):
    engines = {e["name"]: e for e in client.get("/v1alpha1/engines").json()}
    models = {m["modelId"]: m for m in client.get("/v1alpha1/models").json()}
    return {
        "model": {"id": models["qwen3:0.6b"]["id"]},
        "engine": {"id": engines["Ollama"]["id"]},
        "config": {},
        **extra,
    }


def _create(client, **extra):
    response = client.post(
        "/v1alpha1/inferenceInstance", json=_ollama_body(client, **extra)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _get(client, instance_id):
    response = client.get(f"/v1alpha1/inferenceInstance/{instance_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _delete(client, instance_id):
    assert (
        client.delete(f"/v1alpha1/inferenceInstance/{instance_id}").status_code
        == 200
    )


# --- 6.1 status ------------------------------------------------------------


def test_create_starts_pending_and_carries_the_new_fields(inference_env):
    client, _, _ = inference_env
    created = _create(client)
    try:
        assert created["status"] == "Pending"
        assert created["last_error"] is None
        assert created["last_error_at"] is None
        assert created["replicas"] == 1
        assert created["gpu_count"] == 1
        assert created["cpu"] is None
        assert created["memory"] is None
        assert created["stopped_at"] is None
    finally:
        _delete(client, created["id"])


def test_install_failure_keeps_the_row_as_failed_and_answers_500(
    inference_env,
):
    client, controller, _ = inference_env
    controller.install.side_effect = RuntimeError("helm exploded")
    before = {
        i["id"] for i in client.get("/v1alpha1/inferenceInstance").json()
    }

    response = client.post(
        "/v1alpha1/inferenceInstance", json=_ollama_body(client)
    )

    assert response.status_code == 500
    assert "helm exploded" in response.json()["detail"]
    listed = {
        i["id"]: i for i in client.get("/v1alpha1/inferenceInstance").json()
    }
    (new_id,) = set(listed) - before
    try:
        row = listed[new_id]
        assert row["status"] == "Failed"
        assert "helm exploded" in row["last_error"]
        datetime.fromisoformat(row["last_error_at"])
        # The half-created release is uninstalled best effort.
        controller.uninstall.assert_awaited_once()
    finally:
        controller.install.side_effect = None
        _delete(client, new_id)


def test_last_error_is_capped_at_4000_characters(inference_env):
    client, controller, _ = inference_env
    controller.install.side_effect = RuntimeError("x" * 5000)
    before = {
        i["id"] for i in client.get("/v1alpha1/inferenceInstance").json()
    }
    client.post("/v1alpha1/inferenceInstance", json=_ollama_body(client))
    listed = {
        i["id"]: i for i in client.get("/v1alpha1/inferenceInstance").json()
    }
    (new_id,) = set(listed) - before
    try:
        assert len(listed[new_id]["last_error"]) == 4000
    finally:
        controller.install.side_effect = None
        _delete(client, new_id)


def test_poller_marks_a_crashlooping_instance_failed_then_running(
    inference_env,
):
    from api.inference_status import update_all_inference_instance_endpoints

    client, _, pods = inference_env
    created = _create(client)
    try:
        pods.return_value = CRASH
        update_all_inference_instance_endpoints(get_db_direct())
        row = _get(client, created["id"])
        assert row["status"] == "Failed"
        assert row["last_error"] == "CrashLoopBackOff: back-off 5m0s"
        first_at = row["last_error_at"]
        assert first_at

        # Written once per change: the same reason again leaves the stamp.
        update_all_inference_instance_endpoints(get_db_direct())
        assert _get(client, created["id"])["last_error_at"] == first_at

        pods.return_value = READY
        update_all_inference_instance_endpoints(get_db_direct())
        row = _get(client, created["id"])
        assert row["status"] == "Running"
        assert row["ready"] is True
        assert row["last_error"] is None
        assert row["last_error_at"] is None
    finally:
        _delete(client, created["id"])


def test_get_does_not_persist_raw_kubelet_reasons(inference_env):
    client, _, pods = inference_env
    created = _create(client)
    try:
        pods.return_value = PodStatus(False, "ContainerCreating", None)
        row = _get(client, created["id"])
        assert row["status"] == "Pending"
        assert row["ready"] is False
    finally:
        _delete(client, created["id"])


def test_apply_pod_status_keeps_stopped():
    from utils.instance_status import apply_pod_status

    db = mock.Mock()
    row = SimpleNamespace(
        status="Stopped", last_error=None, last_error_at=None
    )
    # The old pod is still terminating with reason Error: Stopped stays.
    assert apply_pod_status(db, row, CRASH) is False
    assert row.status == "Stopped"
    # A pod that still answers Ready while it drains does not either;
    # only resume leaves Stopped.
    assert apply_pod_status(db, row, READY) is False
    assert row.status == "Stopped"
    db.commit.assert_not_called()


@pytest.fixture
def vectordb_env(monkeypatch):
    import api.vectordb_instance as vi

    controller_cls = mock.Mock()
    controller = controller_cls.return_value
    controller.namespace = "ai-stack"
    controller.get_pod_labels.return_value = "app.kubernetes.io/instance=qdrant-abcdef12,app.kubernetes.io/name=qdrant"
    controller.install = mock.AsyncMock()
    controller.uninstall = mock.AsyncMock()
    monkeypatch.setattr(vi, "VectorDBController", controller_cls)
    monkeypatch.setattr(vi, "generate_secret", lambda seed: "s3cret")
    monkeypatch.setattr(vi, "store_credential", mock.Mock())
    monkeypatch.setattr(vi, "delete_credential", mock.Mock())
    monkeypatch.setattr(vi, "get_service_endpoint", lambda *a, **k: None)
    pods = mock.Mock(return_value=NO_PODS)
    monkeypatch.setattr(vi, "get_pod_status_and_readiness", pods)
    return TestClient(create_app()), controller, pods


def _create_vectordb(client):
    vectordb = client.get("/v1alpha1/vectordb").json()[0]
    return client.post(
        "/v1alpha1/vectordb_instances",
        json={"vectorDB": {"id": vectordb["id"]}, "configParams": {}},
    )


def test_vectordb_install_failure_keeps_the_row(vectordb_env):
    client, controller, _ = vectordb_env
    controller.install.side_effect = RuntimeError("helm exploded")
    before = {
        i["id"] for i in client.get("/v1alpha1/vectordb_instances").json()
    }
    response = _create_vectordb(client)
    assert response.status_code == 500
    assert "helm exploded" in response.json()["detail"]
    listed = {
        i["id"]: i for i in client.get("/v1alpha1/vectordb_instances").json()
    }
    (new_id,) = set(listed) - before
    try:
        assert listed[new_id]["status"] == "Failed"
        assert "helm exploded" in listed[new_id]["last_error"]
        controller.uninstall.assert_awaited_once()
    finally:
        controller.install.side_effect = None
        assert (
            client.delete(f"/v1alpha1/vectordb_instances/{new_id}").status_code
            == 204
        )


def test_a_failed_vectordb_upgrade_leaves_the_row_failed(vectordb_env):
    """A failed OIDC re-attach on upgrade can delete the browser route
    (stream C); the row must not keep saying Ready with a stale endpoint."""
    client, controller, _ = vectordb_env
    created = _create_vectordb(client)
    assert created.status_code == 201, created.text
    instance_id = created.json()["id"]
    try:
        controller.upgrade = mock.AsyncMock(
            side_effect=RuntimeError("upgrade exploded")
        )
        response = client.put(
            f"/v1alpha1/vectordb_instances/{instance_id}",
            json=created.json(),
        )
        assert response.status_code == 500
        assert "upgrade exploded" in response.json()["detail"]
        row = client.get(f"/v1alpha1/vectordb_instances/{instance_id}").json()
        assert row["status"] == "Failed"
        assert "upgrade exploded" in row["last_error"]
    finally:
        controller.upgrade = mock.AsyncMock()
        client.delete(f"/v1alpha1/vectordb_instances/{instance_id}")


def test_vectordb_create_starts_pending(vectordb_env):
    client, _, _ = vectordb_env
    response = _create_vectordb(client)
    assert response.status_code == 201, response.text
    try:
        assert response.json()["status"] == "Pending"
    finally:
        client.delete(f"/v1alpha1/vectordb_instances/{response.json()['id']}")


def test_vectordb_poller_commits_a_status_change(vectordb_env):
    """The stale-status loop of update_all_vectordb_instance_endpoints
    persists through the row's own session (object_session(...).commit()
    in check_pod_status_and_readiness), not the poller's own db."""
    from api.vectordb_instance import update_all_vectordb_instance_endpoints

    client, _, pods = vectordb_env
    created = _create_vectordb(client)
    assert created.status_code == 201, created.text
    instance_id = created.json()["id"]
    try:
        assert created.json()["status"] == "Pending"
        pods.return_value = READY
        update_all_vectordb_instance_endpoints(get_db_direct())
        row = client.get(f"/v1alpha1/vectordb_instances/{instance_id}").json()
        assert row["status"] == "Running"
        assert row["ready"] is True
    finally:
        client.delete(f"/v1alpha1/vectordb_instances/{instance_id}")


@pytest.fixture
def notebook_env(monkeypatch):
    import api.notebooks as nb

    controller_cls = mock.Mock()
    controller = controller_cls.return_value
    controller.get_service_name.return_value = "nb-x-kf-notebooks-nb-x"
    controller.get_pod_labels.return_value = (
        "app.kubernetes.io/instance=nb-x,app.kubernetes.io/name=kf-notebooks"
    )
    controller.install = mock.AsyncMock()
    controller.uninstall = mock.AsyncMock()
    monkeypatch.setattr(nb, "NotebooksController", controller_cls)
    monkeypatch.setattr(nb, "get_service_endpoint", lambda *a, **k: None)
    pods = mock.Mock(return_value=NO_PODS)
    monkeypatch.setattr(nb, "get_pod_status_and_readiness", pods)
    return TestClient(create_app()), controller, pods


def _notebook_body(name):
    return {
        "name": name,
        "type": "vscode",
        "framework": "python",
        "nvidia_gpu": False,
    }


def test_notebook_install_failure_keeps_the_row(notebook_env):
    client, controller, _ = notebook_env
    controller.install.side_effect = RuntimeError("helm exploded")
    response = client.post(
        "/v1alpha1/notebooks", json=_notebook_body("ops-failed")
    )
    assert response.status_code == 500
    assert "helm exploded" in response.json()["detail"]
    rows = [
        n
        for n in client.get("/v1alpha1/notebooks").json()
        if n["name"] == "ops-failed"
    ]
    assert len(rows) == 1
    try:
        assert rows[0]["status"] == "Failed"
        assert "helm exploded" in rows[0]["last_error"]
        controller.uninstall.assert_awaited_once()
    finally:
        controller.install.side_effect = None
        assert (
            client.delete(f"/v1alpha1/notebooks/{rows[0]['id']}").status_code
            == 200
        )


def test_a_failed_notebook_upgrade_leaves_the_row_failed(notebook_env):
    """A failed OIDC re-attach on upgrade can delete the browser route
    (stream C); the row must not keep saying Ready with a stale endpoint."""
    client, controller, _ = notebook_env
    created = client.post(
        "/v1alpha1/notebooks", json=_notebook_body("ops-upgrade-failed")
    )
    assert created.status_code == 200, created.text
    notebook_id = created.json()["id"]
    try:
        controller.upgrade = mock.AsyncMock(
            side_effect=RuntimeError("upgrade exploded")
        )
        response = client.put(
            f"/v1alpha1/notebooks/{notebook_id}", json=created.json()
        )
        assert response.status_code == 500
        assert "upgrade exploded" in response.json()["detail"]
        row = client.get(f"/v1alpha1/notebooks/{notebook_id}").json()
        assert row["status"] == "Failed"
        assert "upgrade exploded" in row["last_error"]
    finally:
        controller.upgrade = mock.AsyncMock()
        client.delete(f"/v1alpha1/notebooks/{notebook_id}")


def test_notebook_create_starts_pending(notebook_env):
    client, _, _ = notebook_env
    response = client.post(
        "/v1alpha1/notebooks", json=_notebook_body("ops-pending")
    )
    assert response.status_code == 200, response.text
    try:
        assert response.json()["status"] == "Pending"
    finally:
        client.delete(f"/v1alpha1/notebooks/{response.json()['id']}")


def test_notebook_poller_commits_a_status_change(notebook_env):
    """The stale-status loop of update_all_notebook_instance_endpoints
    persists through the row's own session (object_session(...).commit()
    in check_pod_status_and_readiness), not the poller's own db."""
    from api.notebooks import update_all_notebook_instance_endpoints

    client, _, pods = notebook_env
    created = client.post(
        "/v1alpha1/notebooks", json=_notebook_body("ops-poller")
    )
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    try:
        assert created.json()["status"] == "Pending"
        pods.return_value = READY
        update_all_notebook_instance_endpoints(get_db_direct())
        row = client.get(f"/v1alpha1/notebooks/{instance_id}").json()
        assert row["status"] == "Running"
        assert row["ready"] is True
    finally:
        client.delete(f"/v1alpha1/notebooks/{instance_id}")


# --- 6.2 logs and events ---------------------------------------------------

EVENT_AT = datetime(2026, 9, 6, 10, 0)


def _inspection_clients(monkeypatch, pods, events=()):
    """Mock CoreV1Api/AppsV1Api behind utils.pod_inspection."""
    core = fake_core(
        pods,
        logs={
            (
                p.metadata.name,
                c.name,
                False,
            ): f"log of {p.metadata.name}/{c.name}"
            for p in pods
            for c in p.spec.containers
        },
    )
    core.list_namespaced_event.return_value = fake_listing(*events)
    apps = mock.Mock()
    apps.list_namespaced_deployment.return_value = fake_listing()
    apps.list_namespaced_stateful_set.return_value = fake_listing()
    monkeypatch.setattr(
        "utils.pod_inspection.get_core_v1_client", lambda: core
    )
    monkeypatch.setattr(
        "utils.pod_inspection.get_apps_v1_client", lambda: apps
    )
    return core, apps


def test_inference_logs_and_events(inference_env, monkeypatch):
    client, _, _ = inference_env
    core, _ = _inspection_clients(
        monkeypatch,
        [fake_pod("ollama-abcdef12-0", ("ollama",))],
        [fake_event("Pod", "ollama-abcdef12-0", "Pulled", EVENT_AT)],
    )
    created = _create(client)
    try:
        url = f"/v1alpha1/inferenceInstance/{created['id']}"
        logs = client.get(f"{url}/logs?tail=50")
        assert logs.status_code == 200, logs.text
        assert logs.json() == {
            "pods": [
                {
                    "name": "ollama-abcdef12-0",
                    "containers": [
                        {
                            "name": "ollama",
                            "log": "log of ollama-abcdef12-0/ollama",
                        }
                    ],
                }
            ]
        }
        core.list_namespaced_pod.assert_called_with(
            namespace="ai-stack", label_selector=LABELS
        )
        assert (
            core.read_namespaced_pod_log.call_args.kwargs["tail_lines"] == 50
        )
        assert client.get(f"{url}/logs?tail=0").status_code == 422
        assert client.get(f"{url}/logs?tail=5001").status_code == 422

        events = client.get(f"{url}/events")
        assert events.status_code == 200, events.text
        assert events.json() == [
            {
                "at": EVENT_AT.isoformat(),
                "type": "Normal",
                "reason": "Pulled",
                "message": "m",
                "object": "Pod/ollama-abcdef12-0",
            }
        ]
    finally:
        _delete(client, created["id"])


def test_vectordb_logs_and_events(vectordb_env, monkeypatch):
    client, controller, _ = vectordb_env
    core, _ = _inspection_clients(
        monkeypatch, [fake_pod("qdrant-abcdef12-0", ("qdrant",))]
    )
    created = _create_vectordb(client)
    assert created.status_code == 201, created.text
    instance_id = created.json()["id"]
    try:
        logs = client.get(f"/v1alpha1/vectordb_instances/{instance_id}/logs")
        assert logs.status_code == 200, logs.text
        assert logs.json()["pods"][0]["containers"][0]["name"] == "qdrant"
        core.list_namespaced_pod.assert_called_with(
            namespace="ai-stack",
            label_selector=controller.get_pod_labels.return_value,
        )
        events = client.get(
            f"/v1alpha1/vectordb_instances/{instance_id}/events"
        )
        assert events.status_code == 200
        assert events.json() == []
    finally:
        client.delete(f"/v1alpha1/vectordb_instances/{instance_id}")


def test_notebook_logs_and_events_use_the_notebook_name_label(
    notebook_env, monkeypatch
):
    client, controller, _ = notebook_env
    core, _ = _inspection_clients(monkeypatch, [fake_pod("nb-x-0", ("nb-x",))])
    created = client.post(
        "/v1alpha1/notebooks", json=_notebook_body("ops-logs")
    )
    assert created.status_code == 200, created.text
    notebook_id = created.json()["id"]
    try:
        logs = client.get(f"/v1alpha1/notebooks/{notebook_id}/logs")
        assert logs.status_code == 200, logs.text
        assert logs.json()["pods"][0]["name"] == "nb-x-0"
        core.list_namespaced_pod.assert_called_with(
            namespace="ai-stack",
            label_selector="notebook-name=nb-x-kf-notebooks-nb-x",
        )
        assert (
            client.get(f"/v1alpha1/notebooks/{notebook_id}/events").json()
            == []
        )
    finally:
        client.delete(f"/v1alpha1/notebooks/{notebook_id}")


def test_logs_and_events_answer_404_outside_the_organization(
    oidc_client,  # noqa: F811
    tokens,  # noqa: F811
    other_org,  # noqa: F811
):
    from models.inference_instance import DBInferenceInstance
    from models.notebook import Notebook
    from models.vectordb_instance import DBVectorDBInstance

    headers = tokens["alice"]
    # The columns are UUID(as_uuid=True): SQLite's bind processor wants
    # uuid.UUID values, not the strings the API answers with.
    model_id = uuid.UUID(
        oidc_client.get(MODELS, headers=headers).json()[0]["id"]
    )
    engine_id = uuid.UUID(
        oidc_client.get("/v1alpha1/engines", headers=headers).json()[0]["id"]
    )
    vectordb_id = uuid.UUID(
        oidc_client.get("/v1alpha1/vectordb", headers=headers).json()[0]["id"]
    )
    # Make sure bob exists before his id is used as an owner.
    oidc_client.get(NOTEBOOKS, headers=tokens["bob"])
    foreign_instance = add_row(
        DBInferenceInstance(
            model_id=model_id, engine_id=engine_id, org_id=other_org
        )
    )
    foreign_vectordb = add_row(
        DBVectorDBInstance(vectordb_id=vectordb_id, org_id=other_org)
    )
    bobs_notebook = add_row(
        Notebook(
            name="bobs-nb",
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
            org_id=default_org_id(),
            owner_id=user_id("bob"),
        )
    )
    try:
        for url, detail in (
            (
                f"/v1alpha1/inferenceInstance/{foreign_instance}",
                "Inference instance not found",
            ),
            (
                f"/v1alpha1/vectordb_instances/{foreign_vectordb}",
                "Vector database instance not found",
            ),
            (f"/v1alpha1/notebooks/{bobs_notebook}", "Notebook not found"),
        ):
            for suffix in ("/logs", "/events"):
                denied = oidc_client.get(url + suffix, headers=headers)
                assert denied.status_code == 404, (url + suffix, denied.text)
                assert denied.json()["detail"] == detail
    finally:
        delete_rows(DBInferenceInstance, foreign_instance)
        delete_rows(DBVectorDBInstance, foreign_vectordb)
        delete_rows(Notebook, bobs_notebook)


# --- 6.3 launch resources --------------------------------------------------


def test_create_stores_the_launch_resources(inference_env):
    client, _, _ = inference_env
    created = _create(client, gpu_count=2, replicas=3, cpu="4", memory="16Gi")
    try:
        assert created["gpu_count"] == 2
        assert created["replicas"] == 3
        assert created["cpu"] == "4"
        assert created["memory"] == "16Gi"
        row = _get(client, created["id"])
        assert (row["gpu_count"], row["replicas"]) == (2, 3)
    finally:
        _delete(client, created["id"])


def test_create_turns_empty_cpu_and_memory_into_null(inference_env):
    client, _, _ = inference_env
    created = _create(client, cpu="", memory="")
    try:
        assert created["cpu"] is None
        assert created["memory"] is None
    finally:
        _delete(client, created["id"])


@pytest.mark.parametrize(
    "extra",
    [
        {"replicas": 0},
        {"replicas": 17},
        {"gpu_count": 0},
        {"gpu_count": 9},
        {"cpu": "lots"},
        {"memory": "16 Gi"},
    ],
)
def test_create_rejects_out_of_range_resources(inference_env, extra):
    client, _, _ = inference_env
    response = client.post(
        "/v1alpha1/inferenceInstance", json=_ollama_body(client, **extra)
    )
    assert response.status_code == 422, response.text


def test_put_leaves_gpu_count_unchanged(inference_env):
    """READ_ONLY_STATUS_FIELDS covers gpu_count (and replicas/cpu/memory):
    a PUT carrying a new value must not reach the row, the same as status."""
    client, _, _ = inference_env
    created = _create(client, gpu_count=2)
    url = f"/v1alpha1/inferenceInstance/{created['id']}"
    try:
        payload = dict(created)
        payload["gpu_count"] = -5
        response = client.put(url, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["gpu_count"] == 2
        assert _get(client, created["id"])["gpu_count"] == 2
    finally:
        _delete(client, created["id"])


# --- 6.3 actions -----------------------------------------------------------


def _overrides(controller):
    return controller.upgrade.await_args.kwargs["overrides"]


def test_stop_resume_and_scale_change_the_helm_values(inference_env):
    client, controller, _ = inference_env
    created = _create(client, replicas=2)
    url = f"/v1alpha1/inferenceInstance/{created['id']}"
    try:
        stopped = client.post(f"{url}/stop")
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "Stopped"
        assert stopped.json()["stopped_at"]
        assert stopped.json()["replicas"] == 2
        assert _overrides(controller) == {"replicaCount": 0}
        # The row keeps its LiteLLM name (None here: no proxy configured).
        assert "litellm_model_name" in stopped.json()

        resumed = client.post(f"{url}/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "Pending"
        assert resumed.json()["stopped_at"] is None
        assert _overrides(controller) == {"replicaCount": 2}

        scaled = client.post(f"{url}/scale", json={"replicas": 3})
        assert scaled.status_code == 200, scaled.text
        assert scaled.json()["replicas"] == 3
        assert scaled.json()["status"] == "Pending"
        assert _overrides(controller) == {"replicaCount": 3}
        # The rendered values see the new count: the schema passed to
        # upgrade carries replicas=3.
        assert controller.upgrade.await_args.args[0].replicas == 3

        to_zero = client.post(f"{url}/scale", json={"replicas": 0})
        assert to_zero.status_code == 200, to_zero.text
        assert to_zero.json()["status"] == "Stopped"
        assert to_zero.json()["replicas"] == 3
        assert _overrides(controller) == {"replicaCount": 0}

        # A lingering error from before the stop must not survive a scale
        # back up, exactly like resume (spec 6.3): scale shares resume's
        # "leave Stopped" bookkeeping.
        from models.inference_instance import DBInferenceInstance
        from utils.instance_status import utcnow

        direct = get_db_direct()
        row = (
            direct.query(DBInferenceInstance)
            .filter(DBInferenceInstance.id == uuid.UUID(created["id"]))
            .first()
        )
        row.last_error, row.last_error_at = "boom", utcnow()
        direct.commit()

        scaled_up = client.post(f"{url}/scale", json={"replicas": 4})
        assert scaled_up.status_code == 200, scaled_up.text
        assert scaled_up.json()["status"] == "Pending"
        assert scaled_up.json()["last_error"] is None
        assert scaled_up.json()["last_error_at"] is None
        assert _overrides(controller) == {"replicaCount": 4}

        assert (
            client.post(f"{url}/scale", json={"replicas": 17}).status_code
            == 422
        )
        assert (
            client.post(f"{url}/scale", json={"replicas": -1}).status_code
            == 422
        )
        assert controller.upgrade.await_count == 5
    finally:
        _delete(client, created["id"])


def test_a_failed_helm_upgrade_leaves_the_row_unchanged(inference_env):
    client, controller, _ = inference_env
    created = _create(client)
    url = f"/v1alpha1/inferenceInstance/{created['id']}"
    try:
        controller.upgrade.side_effect = RuntimeError("helm exploded")
        response = client.post(f"{url}/stop")
        assert response.status_code == 500
        assert "helm exploded" in response.json()["detail"]
        row = _get(client, created["id"])
        assert row["status"] == "Pending"
        assert row["stopped_at"] is None
    finally:
        controller.upgrade.side_effect = None
        _delete(client, created["id"])


def test_a_gateway_failure_on_stop_says_so_and_leaves_the_row(
    inference_env,
):
    """A gateway failure is reported as itself, not as a Helm failure.

    The row is left alone on purpose. Marking it Failed here does not
    survive: the workload is healthy (Helm succeeded), so the 5 s poller
    sees Ready pods and apply_pod_status writes Running back and clears
    last_error within one tick. Recording a status the poller erases
    would be worse than recording none; the gap is in ADR 0002.
    """
    client, controller, _ = inference_env
    created = _create(client)
    url = f"/v1alpha1/inferenceInstance/{created['id']}"
    try:
        controller.upgrade.side_effect = ApiKeyPolicyError(
            "HTTPRoute ai-stack/inf-1 could not get SecurityPolicy inf-1"
        )
        response = client.post(f"{url}/stop")
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail.startswith("Failed to protect the gateway route")
        assert "Helm" not in detail
        row = _get(client, created["id"])
        assert row["status"] == "Pending"
    finally:
        controller.upgrade.side_effect = None
        _delete(client, created["id"])


def test_a_failed_scale_leaves_the_stored_replicas_and_status_unchanged(
    inference_env,
):
    client, controller, _ = inference_env
    created = _create(client, replicas=2)
    url = f"/v1alpha1/inferenceInstance/{created['id']}"
    try:
        controller.upgrade.side_effect = RuntimeError("helm exploded")
        response = client.post(f"{url}/scale", json={"replicas": 5})
        assert response.status_code == 500
        assert "helm exploded" in response.json()["detail"]
        row = _get(client, created["id"])
        assert row["replicas"] == 2
        assert row["status"] == "Pending"
    finally:
        controller.upgrade.side_effect = None
        _delete(client, created["id"])


def test_restart_on_a_stopped_instance_is_blocked(inference_env, monkeypatch):
    import api.instance_inspection as inspection

    client, controller, _ = inference_env
    restart = mock.Mock(return_value="Deployment/ollama-abcdef12")
    monkeypatch.setattr(inspection, "restart_workload", restart)
    created = _create(client)
    url = f"/v1alpha1/inferenceInstance/{created['id']}"
    try:
        stopped = client.post(f"{url}/stop")
        assert stopped.status_code == 200, stopped.text
        stopped_at = stopped.json()["stopped_at"]

        blocked = client.post(f"{url}/restart")
        assert blocked.status_code == 409, blocked.text
        assert (
            blocked.json()["detail"]
            == "The instance is stopped; resume it first"
        )
        restart.assert_not_called()
        row = _get(client, created["id"])
        assert row["status"] == "Stopped"
        assert row["stopped_at"] == stopped_at

        # Stop is idempotent: stopping an already-Stopped row leaves
        # stopped_at and the Helm release alone.
        again = client.post(f"{url}/stop")
        assert again.status_code == 200, again.text
        assert again.json()["stopped_at"] == stopped_at
        assert controller.upgrade.await_count == 1
    finally:
        _delete(client, created["id"])


def test_restart_patches_the_workload_and_resets_the_status(
    inference_env, monkeypatch
):
    import api.instance_inspection as inspection

    client, _, pods = inference_env
    restart = mock.Mock(return_value="Deployment/ollama-abcdef12")
    monkeypatch.setattr(inspection, "restart_workload", restart)
    created = _create(client)
    url = f"/v1alpha1/inferenceInstance/{created['id']}"
    try:
        pods.return_value = CRASH
        assert _get(client, created["id"])["status"] == "Failed"
        pods.return_value = NO_PODS

        restarted = client.post(f"{url}/restart")
        assert restarted.status_code == 200, restarted.text
        assert restarted.json()["status"] == "Pending"
        assert restarted.json()["last_error"] is None
        restart.assert_called_once_with("ai-stack", LABELS)

        restart.side_effect = LookupError("nothing to restart")
        assert client.post(f"{url}/restart").status_code == 409
    finally:
        _delete(client, created["id"])


def test_vectordb_restart(vectordb_env, monkeypatch):
    import api.instance_inspection as inspection

    client, controller, _ = vectordb_env
    restart = mock.Mock(return_value="StatefulSet/qdrant-abcdef12")
    monkeypatch.setattr(inspection, "restart_workload", restart)
    created = _create_vectordb(client)
    assert created.status_code == 201, created.text
    instance_id = created.json()["id"]
    try:
        restarted = client.post(
            f"/v1alpha1/vectordb_instances/{instance_id}/restart"
        )
        assert restarted.status_code == 200, restarted.text
        assert restarted.json()["status"] == "Pending"
        restart.assert_called_once_with(
            "ai-stack", controller.get_pod_labels.return_value
        )
    finally:
        client.delete(f"/v1alpha1/vectordb_instances/{instance_id}")


def test_actions_need_the_write_policy(oidc_client, tokens):  # noqa: F811
    from models.inference_instance import DBInferenceInstance

    headers = tokens["alice"]
    model_id = uuid.UUID(
        oidc_client.get(MODELS, headers=headers).json()[0]["id"]
    )
    engine_id = uuid.UUID(
        oidc_client.get("/v1alpha1/engines", headers=headers).json()[0]["id"]
    )
    oidc_client.get(NOTEBOOKS, headers=tokens["bob"])
    bobs = add_row(
        DBInferenceInstance(
            model_id=model_id,
            engine_id=engine_id,
            org_id=default_org_id(),
            owner_id=user_id("bob"),
        )
    )
    try:
        for verb, body in (
            ("restart", None),
            ("stop", None),
            ("resume", None),
            ("scale", {"replicas": 2}),
        ):
            denied = oidc_client.post(
                f"/v1alpha1/inferenceInstance/{bobs}/{verb}",
                headers=headers,
                json=body,
            )
            assert denied.status_code == 403, (verb, denied.text)
    finally:
        delete_rows(DBInferenceInstance, bobs)


def test_list_tolerates_a_kept_row_whose_engine_is_gone(
    oidc_client,  # noqa: F811
    tokens,  # noqa: F811
):
    """A launch that failed before its chart existed stays as a Failed row;
    the list and the detail keep its status instead of answering 500."""
    from models.inference_instance import DBInferenceInstance

    headers = tokens["carol"]
    # Ollama has no reranker chart in the seed, so this pair has an engine
    # row but no chart row: the request path must not raise for it.
    models = oidc_client.get("/v1alpha1/models", headers=headers).json()
    reranker = next(m for m in models if m["category"] == "reranker")
    engines = oidc_client.get("/v1alpha1/engines", headers=headers).json()
    ollama = next(e for e in engines if e["name"] == "Ollama")
    orphan = add_row(
        DBInferenceInstance(
            model_id=uuid.UUID(reranker["id"]),
            engine_id=uuid.UUID(ollama["id"]),
            org_id=default_org_id(),
            status="Failed",
            last_error="helm install failed",
        )
    )
    try:
        listed = oidc_client.get(
            "/v1alpha1/inferenceInstance", headers=headers
        )
        assert listed.status_code == 200, listed.text
        row = next(i for i in listed.json() if i["id"] == str(orphan))
        assert row["status"] == "Failed"
        assert row["ready"] is False
        detail = oidc_client.get(
            f"/v1alpha1/inferenceInstance/{orphan}", headers=headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["last_error"] == "helm install failed"
    finally:
        delete_rows(DBInferenceInstance, orphan)


def test_a_failed_row_is_deletable_without_a_cluster(
    oidc_client,  # noqa: F811
    tokens,  # noqa: F811
    monkeypatch,
):
    """A launch that failed because the cluster was unreachable leaves a
    Failed row; deleting it must not need a controller. A Running row
    keeps the strict behaviour (500, row kept)."""
    import api.inference_instance as ii
    from models.inference_instance import DBInferenceInstance
    from models.workload_credential import WorkloadCredential

    headers = tokens["carol"]
    models = oidc_client.get("/v1alpha1/models", headers=headers).json()
    llm = next(m for m in models if m["category"] == "llm")
    engines = oidc_client.get("/v1alpha1/engines", headers=headers).json()
    ollama = next(e for e in engines if e["name"] == "Ollama")

    def boom(name):
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(ii, "get_controller", boom)
    monkeypatch.setattr(ii, "unregister_instance", lambda instance: None)
    # Without a cluster delete_credential raises before it reaches the
    # bookkeeping row; the row must still go with the instance.
    delete_credential = mock.Mock(side_effect=RuntimeError("no cluster"))
    monkeypatch.setattr(ii, "delete_credential", delete_credential)

    failed = add_row(
        DBInferenceInstance(
            model_id=uuid.UUID(llm["id"]),
            engine_id=uuid.UUID(ollama["id"]),
            org_id=default_org_id(),
            status="Failed",
            last_error="500: Failed to load Kubernetes configuration",
        )
    )
    # The credential was stored before the install failed: its row says
    # where the Secrets are, and the delete must still remove them.
    credential = add_row(
        WorkloadCredential(
            resource_kind="inf",
            resource_id=failed,
            namespace="custom-ns",
            secret_name="inf-x-credentials",
            apikey_secret_name="inf-x-apikey-auth",
        )
    )
    running = add_row(
        DBInferenceInstance(
            model_id=uuid.UUID(llm["id"]),
            engine_id=uuid.UUID(ollama["id"]),
            org_id=default_org_id(),
            status="Running",
        )
    )
    try:
        gone = oidc_client.delete(
            f"/v1alpha1/inferenceInstance/{failed}", headers=headers
        )
        assert gone.status_code == 200, gone.text
        with get_db_direct() as db:
            assert db.get(DBInferenceInstance, failed) is None
            assert db.get(WorkloadCredential, credential) is None
        delete_credential.assert_called_once()
        assert delete_credential.call_args.args[1:] == (
            "custom-ns",
            "inf",
            failed,
        )

        kept = oidc_client.delete(
            f"/v1alpha1/inferenceInstance/{running}", headers=headers
        )
        assert kept.status_code == 500, kept.text
        with get_db_direct() as db:
            assert db.get(DBInferenceInstance, running) is not None
    finally:
        delete_rows(DBInferenceInstance, running)
        delete_rows(WorkloadCredential, credential)


def test_a_failed_vectordb_row_is_deletable_without_a_cluster(
    oidc_client,  # noqa: F811
    tokens,  # noqa: F811
    monkeypatch,
):
    """Same as the inference rule: a Failed vector database row is
    deleted even when the controller cannot be built, and its credential
    Secrets are still removed (the namespace comes from the credential
    row, else the default). A Running row keeps the strict behaviour."""
    import api.vectordb_instance as vi
    from models.vectordb_instance import DBVectorDBInstance
    from models.workload_credential import WorkloadCredential

    headers = tokens["carol"]
    vectordb_id = uuid.UUID(
        oidc_client.get("/v1alpha1/vectordb", headers=headers).json()[0]["id"]
    )

    def boom(*args, **kwargs):
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(vi, "VectorDBController", boom)
    # Without a cluster delete_credential raises before it reaches the
    # bookkeeping row; the row must still go with the instance.
    delete_credential = mock.Mock(side_effect=RuntimeError("no cluster"))
    monkeypatch.setattr(vi, "delete_credential", delete_credential)

    failed = add_row(
        DBVectorDBInstance(
            vectordb_id=vectordb_id,
            org_id=default_org_id(),
            status="Failed",
            last_error="no kubeconfig",
        )
    )
    credential = add_row(
        WorkloadCredential(
            resource_kind="vdb",
            resource_id=failed,
            namespace="custom-ns",
            secret_name="vdb-x-credentials",
            apikey_secret_name="vdb-x-apikey-auth",
        )
    )
    no_credential = add_row(
        DBVectorDBInstance(
            vectordb_id=vectordb_id, org_id=default_org_id(), status="Failed"
        )
    )
    running = add_row(
        DBVectorDBInstance(
            vectordb_id=vectordb_id, org_id=default_org_id(), status="Running"
        )
    )
    try:
        gone = oidc_client.delete(
            f"/v1alpha1/vectordb_instances/{failed}", headers=headers
        )
        assert gone.status_code == 204, gone.text
        with get_db_direct() as db:
            assert db.get(DBVectorDBInstance, failed) is None
            assert db.get(WorkloadCredential, credential) is None
        assert delete_credential.call_args.args[1:] == (
            "custom-ns",
            "vdb",
            failed,
        )

        # Without a credential row the default namespace is tried.
        gone = oidc_client.delete(
            f"/v1alpha1/vectordb_instances/{no_credential}", headers=headers
        )
        assert gone.status_code == 204, gone.text
        assert delete_credential.call_args.args[1:] == (
            "ai-stack",
            "vdb",
            no_credential,
        )
        with get_db_direct() as db:
            assert db.get(DBVectorDBInstance, no_credential) is None

        with pytest.raises(RuntimeError, match="no kubeconfig"):
            oidc_client.delete(
                f"/v1alpha1/vectordb_instances/{running}", headers=headers
            )
        with get_db_direct() as db:
            assert db.get(DBVectorDBInstance, running) is not None
    finally:
        delete_rows(DBVectorDBInstance, failed, no_credential, running)
        delete_rows(WorkloadCredential, credential)


def test_a_failed_vectordb_row_is_deletable_when_uninstall_fails(
    vectordb_env,
):
    """With a controller but a failing uninstall: a Failed row goes,
    a Pending one answers 500 and stays.

    Picks its own Failed row by the before/after id-set pattern (a
    Failed row leaked by an earlier test in the same per-run database
    must not be picked instead), and deletes every row it created."""
    client, controller, _ = vectordb_env
    controller.install.side_effect = RuntimeError("helm exploded")
    before = {
        i["id"] for i in client.get("/v1alpha1/vectordb_instances").json()
    }
    response = _create_vectordb(client)
    assert response.status_code == 500
    listed = {
        i["id"]: i for i in client.get("/v1alpha1/vectordb_instances").json()
    }
    (failed,) = set(listed) - before
    assert listed[failed]["status"] == "Failed"
    controller.install.side_effect = None
    pending = _create_vectordb(client).json()["id"]
    try:
        controller.uninstall.side_effect = RuntimeError("release is stuck")
        gone = client.delete(f"/v1alpha1/vectordb_instances/{failed}")
        assert gone.status_code == 204, gone.text
        kept = client.delete(f"/v1alpha1/vectordb_instances/{pending}")
        assert kept.status_code == 500, kept.text
        assert "release is stuck" in kept.json()["detail"]
        assert (
            client.get(f"/v1alpha1/vectordb_instances/{pending}").status_code
            == 200
        )
    finally:
        controller.uninstall.side_effect = None
        # The delete under test is idempotent: a 404 here just means the
        # assertion above already removed the row.
        client.delete(f"/v1alpha1/vectordb_instances/{failed}")
        client.delete(f"/v1alpha1/vectordb_instances/{pending}")


def test_a_failed_notebook_is_deletable_without_a_cluster(
    oidc_client,  # noqa: F811
    tokens,  # noqa: F811
    monkeypatch,
):
    """A Failed notebook row is deleted when the controller cannot be
    built or the uninstall fails; a Running one keeps the strict rule."""
    import api.notebooks as nb
    from models.notebook import Notebook

    headers = tokens["carol"]

    def boom(*args, **kwargs):
        raise RuntimeError("no kubeconfig")

    monkeypatch.setattr(nb, "NotebooksController", boom)

    def notebook(name, status):
        return Notebook(
            name=name,
            namespace="ai-stack",
            type="vscode",
            nvidia_gpu=False,
            org_id=default_org_id(),
            owner_id=user_id("carol"),
            status=status,
        )

    failed = add_row(notebook("ops-failed-nb", "Failed"))
    stuck = add_row(notebook("ops-stuck-nb", "Failed"))
    running = add_row(notebook("ops-running-nb", "Running"))
    try:
        gone = oidc_client.delete(
            f"/v1alpha1/notebooks/{failed}", headers=headers
        )
        assert gone.status_code == 200, gone.text
        with get_db_direct() as db:
            assert db.get(Notebook, failed) is None

        with pytest.raises(RuntimeError, match="no kubeconfig"):
            oidc_client.delete(
                f"/v1alpha1/notebooks/{running}", headers=headers
            )
        with get_db_direct() as db:
            assert db.get(Notebook, running) is not None

        # A controller whose uninstall fails: the Failed row still goes.
        controller_cls = mock.Mock()
        controller_cls.return_value.uninstall = mock.AsyncMock(
            side_effect=RuntimeError("release is stuck")
        )
        monkeypatch.setattr(nb, "NotebooksController", controller_cls)
        gone = oidc_client.delete(
            f"/v1alpha1/notebooks/{stuck}", headers=headers
        )
        assert gone.status_code == 200, gone.text
        with get_db_direct() as db:
            assert db.get(Notebook, stuck) is None
    finally:
        delete_rows(Notebook, failed, stuck, running)


def test_the_response_carries_the_in_cluster_url_and_the_key_rule(
    inference_env,
):
    """Both drive what the UI tells someone wiring a client up.

    clusterEndpoint is the address a caller inside the cluster must use,
    because the gateway host resolves to 127.0.0.1 there. workloadChecks-
    ApiKey says whether that caller still needs the key: skipping the
    gateway skips its check, but vLLM reads the key itself, so the answer
    is per engine and the UI must not guess it from the engine name.
    """
    client, controller, _ = inference_env
    created = _create(client)
    try:
        row = _get(client, created["id"])
        assert (
            row["clusterEndpoint"] == "http://ollama-abcdef12.ai-stack.svc:80"
        )
        assert row["workloadChecksApiKey"] is False

        controller.workload_checks_api_key = True
        assert _get(client, created["id"])["workloadChecksApiKey"] is True
    finally:
        controller.workload_checks_api_key = False
        _delete(client, created["id"])
