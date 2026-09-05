import pytest

from utils import secret_store as ss


def test_memory_store_round_trip(monkeypatch):
    monkeypatch.setenv("AIOPS_SECRET_STORE", "memory")
    store = ss.get_secret_store()
    assert isinstance(store, ss.MemorySecretStore)
    store.write("ns", "prov-1-credentials", {"api-key": "sk-x"})
    assert store.read("ns", "prov-1-credentials", "api-key") == "sk-x"
    assert store.read("ns", "prov-1-credentials", "other") is None
    assert store.read("ns", "missing", "api-key") is None
    store.delete("ns", "prov-1-credentials")
    store.delete("ns", "prov-1-credentials")  # idempotent
    assert store.read("ns", "prov-1-credentials", "api-key") is None


def test_memory_store_needs_test_mode(monkeypatch):
    monkeypatch.setenv("AIOPS_SECRET_STORE", "memory")
    monkeypatch.setenv("TEST_MODE", "false")
    with pytest.raises(RuntimeError):
        ss.get_secret_store()


def test_kubernetes_store_reads_and_deletes(monkeypatch):
    import base64
    from unittest import mock

    from kubernetes.client.exceptions import ApiException

    core = mock.Mock()
    secret = mock.Mock()
    secret.data = {"api-key": base64.b64encode(b"sk-k").decode()}
    core.read_namespaced_secret.return_value = secret
    store = ss.KubernetesSecretStore(core)
    assert store.read("ns", "n", "api-key") == "sk-k"
    core.read_namespaced_secret.side_effect = ApiException(status=404)
    assert store.read("ns", "n", "api-key") is None
    core.delete_namespaced_secret.side_effect = ApiException(status=404)
    store.delete("ns", "n")  # 404 is fine
    store.write("ns", "n", {"api-key": "v"})
    assert core.create_namespaced_secret.called
