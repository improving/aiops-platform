import uuid
from unittest import mock

import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from utils import gateway

# TEST_MODE deterministic id: hex is
# "00000000000040008134d6e500000001", so id8() (the last eight hex
# characters) is "00000001".
ID = uuid.UUID("00000000-0000-4000-8134-d6e500000001")


@pytest.fixture(autouse=True)
def clear_gateway_env(monkeypatch):
    monkeypatch.delenv("AIOPS_PARENT_DOMAIN", raising=False)
    monkeypatch.delenv("AIOPS_GATEWAY_NAME", raising=False)
    monkeypatch.delenv("AIOPS_GATEWAY_NAMESPACE", raising=False)


def test_gateway_settings_none_without_parent_domain():
    assert gateway.gateway_settings() is None


def test_gateway_settings_defaults(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    assert gateway.gateway_settings() == gateway.GatewaySettings(
        parent_domain="127.0.0.1.nip.io",
        gateway_name="aiops",
        gateway_namespace="envoy-gateway-system",
    )


def test_gateway_settings_overridden(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "example.test")
    monkeypatch.setenv("AIOPS_GATEWAY_NAME", "gw")
    monkeypatch.setenv("AIOPS_GATEWAY_NAMESPACE", "gw-ns")
    settings = gateway.gateway_settings()
    assert settings.parent_domain == "example.test"
    assert settings.gateway_name == "gw"
    assert settings.gateway_namespace == "gw-ns"


def test_id8_is_last_eight_hex_chars():
    assert gateway.id8(ID) == "00000001"


def test_instance_hostname_none_without_settings():
    assert gateway.instance_hostname("nb", ID) is None


def test_instance_hostname(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    assert (
        gateway.instance_hostname("nb", ID) == "nb-00000001.127.0.0.1.nip.io"
    )


def test_instance_hostname_with_suffix(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    assert (
        gateway.instance_hostname("vdb", ID, suffix="-api")
        == "vdb-00000001-api.127.0.0.1.nip.io"
    )


def test_instance_url_none_without_settings():
    assert gateway.instance_url("vdb", ID) is None


def test_instance_url_default_path(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    assert (
        gateway.instance_url("vdb", ID)
        == "https://vdb-00000001.127.0.0.1.nip.io/"
    )


def test_instance_url_with_path(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    url = gateway.instance_url("nb", ID, "/notebook/ai-stack/svc/lab")
    assert (
        url == "https://nb-00000001.127.0.0.1.nip.io/notebook/ai-stack/svc/lab"
    )


def test_instance_url_with_suffix(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    assert (
        gateway.instance_url("vdb", ID, suffix="-api")
        == "https://vdb-00000001-api.127.0.0.1.nip.io/"
    )


def test_ensure_http_route_no_op_without_settings():
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    gateway.ensure_http_route(
        "ai-stack",
        "qdrant-abc",
        "vdb-1.example.test",
        "qdrant-abc",
        6333,
        api_instance=api_instance,
    )
    api_instance.get_namespaced_custom_object.assert_not_called()
    api_instance.create_namespaced_custom_object.assert_not_called()
    api_instance.patch_namespaced_custom_object.assert_not_called()


def test_ensure_http_route_creates_when_missing(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    api_instance.get_namespaced_custom_object.side_effect = ApiException(
        status=404
    )
    gateway.ensure_http_route(
        "ai-stack",
        "qdrant-abc",
        "vdb-00000001.127.0.0.1.nip.io",
        "qdrant-abc",
        6333,
        api_instance=api_instance,
    )
    api_instance.patch_namespaced_custom_object.assert_not_called()
    api_instance.create_namespaced_custom_object.assert_called_once()
    args, _ = api_instance.create_namespaced_custom_object.call_args
    group, version, namespace, plural, body = args
    assert (group, version, namespace, plural) == (
        "gateway.networking.k8s.io",
        "v1",
        "ai-stack",
        "httproutes",
    )
    assert body["metadata"]["name"] == "qdrant-abc"
    assert body["metadata"]["namespace"] == "ai-stack"
    assert body["metadata"]["labels"] == {
        "app.kubernetes.io/managed-by": "aiops"
    }
    assert body["spec"]["hostnames"] == ["vdb-00000001.127.0.0.1.nip.io"]
    assert body["spec"]["parentRefs"] == [
        {"name": "aiops", "namespace": "envoy-gateway-system"}
    ]
    assert body["spec"]["rules"] == [
        {"backendRefs": [{"name": "qdrant-abc", "port": 6333}]}
    ]


def test_ensure_http_route_patches_when_present(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    api_instance.get_namespaced_custom_object.return_value = {
        "metadata": {"name": "qdrant-abc"}
    }
    gateway.ensure_http_route(
        "ai-stack",
        "qdrant-abc",
        "vdb-00000001.127.0.0.1.nip.io",
        "qdrant-abc",
        6333,
        api_instance=api_instance,
    )
    api_instance.create_namespaced_custom_object.assert_not_called()
    api_instance.patch_namespaced_custom_object.assert_called_once()
    args, _ = api_instance.patch_namespaced_custom_object.call_args
    group, version, namespace, plural, name, body = args
    assert (group, version, namespace, plural, name) == (
        "gateway.networking.k8s.io",
        "v1",
        "ai-stack",
        "httproutes",
        "qdrant-abc",
    )
    assert body["spec"]["hostnames"] == ["vdb-00000001.127.0.0.1.nip.io"]


def test_ensure_http_route_propagates_non_404(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    api_instance.get_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    with pytest.raises(ApiException):
        gateway.ensure_http_route(
            "ai-stack",
            "qdrant-abc",
            "vdb-00000001.127.0.0.1.nip.io",
            "qdrant-abc",
            6333,
            api_instance=api_instance,
        )


def test_delete_http_route_no_op_without_settings():
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    gateway.delete_http_route(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.delete_namespaced_custom_object.assert_not_called()


def test_delete_http_route_deletes(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    gateway.delete_http_route(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.delete_namespaced_custom_object.assert_called_once_with(
        "gateway.networking.k8s.io",
        "v1",
        "ai-stack",
        "httproutes",
        "qdrant-abc",
    )


def test_delete_http_route_swallows_404(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    api_instance.delete_namespaced_custom_object.side_effect = ApiException(
        status=404
    )
    gateway.delete_http_route(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )  # does not raise


def test_delete_http_route_propagates_non_404(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    api_instance.delete_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    with pytest.raises(ApiException):
        gateway.delete_http_route(
            "ai-stack", "qdrant-abc", api_instance=api_instance
        )


# --- Task 10: policies, grants, secrets -------------------------------------

SP = ("gateway.envoyproxy.io", "v1alpha1", "ai-stack", "securitypolicies")
BTP = (
    "gateway.envoyproxy.io",
    "v1alpha1",
    "ai-stack",
    "backendtrafficpolicies",
)


@pytest.fixture
def gateway_env(monkeypatch):
    monkeypatch.setenv("AIOPS_PARENT_DOMAIN", "127.0.0.1.nip.io")
    monkeypatch.setenv(
        "OIDC_ISSUER", "https://auth.127.0.0.1.nip.io/realms/aiops"
    )


def _api(get=None):
    api_instance = mock.Mock(spec=client.CustomObjectsApi)
    if get is None:
        api_instance.get_namespaced_custom_object.side_effect = ApiException(
            status=404
        )
    else:
        api_instance.get_namespaced_custom_object.return_value = get
    return api_instance


def _ref(name):
    return {
        "group": "gateway.networking.k8s.io",
        "kind": "HTTPRoute",
        "name": name,
    }


def test_sso_hostname_and_redirect_url(gateway_env):
    assert gateway.sso_hostname() == "sso.127.0.0.1.nip.io"
    assert (
        gateway.oidc_redirect_url()
        == "https://sso.127.0.0.1.nip.io/oauth2/callback"
    )


def test_sso_hostname_none_without_settings():
    assert gateway.sso_hostname() is None
    assert gateway.oidc_redirect_url() is None


def test_oidc_issuer_from_auth_settings(gateway_env, monkeypatch):
    assert (
        gateway.oidc_issuer() == "https://auth.127.0.0.1.nip.io/realms/aiops"
    )
    monkeypatch.setenv("OIDC_ISSUER", "https://kc.example.test/realms/x")
    assert gateway.oidc_issuer() == "https://kc.example.test/realms/x"


def test_oidc_issuer_falls_back_to_parent_domain(gateway_env, monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER")
    assert (
        gateway.oidc_issuer() == "https://auth.127.0.0.1.nip.io/realms/aiops"
    )


def test_apikey_secret_name():
    assert gateway.apikey_secret_name("vdb", ID) == "vdb-00000001-apikey-auth"


def test_ensure_security_policy_no_op_without_settings():
    api_instance = _api()
    gateway.ensure_security_policy(
        "ai-stack",
        "p",
        "r",
        "oidc",
        "sso.example.test",
        api_instance=api_instance,
    )
    api_instance.get_namespaced_custom_object.assert_not_called()
    api_instance.create_namespaced_custom_object.assert_not_called()


def test_ensure_security_policy_oidc_body(gateway_env):
    api_instance = _api()
    gateway.ensure_security_policy(
        "ai-stack",
        "aiops-workloads-oidc",
        "sso",
        "oidc",
        "sso.127.0.0.1.nip.io",
        api_instance=api_instance,
    )
    api_instance.create_namespaced_custom_object.assert_called_once()
    args, _ = api_instance.create_namespaced_custom_object.call_args
    assert args[:4] == SP
    body = args[4]
    assert body["apiVersion"] == "gateway.envoyproxy.io/v1alpha1"
    assert body["kind"] == "SecurityPolicy"
    assert body["metadata"] == {
        "name": "aiops-workloads-oidc",
        "namespace": "ai-stack",
        "labels": {"app.kubernetes.io/managed-by": "aiops"},
    }
    assert body["spec"]["targetRefs"] == [_ref("sso")]
    oidc = body["spec"]["oidc"]
    issuer = "https://auth.127.0.0.1.nip.io/realms/aiops"
    assert oidc["provider"] == {
        "issuer": issuer,
        "authorizationEndpoint": f"{issuer}/protocol/openid-connect/auth",
        "tokenEndpoint": f"{issuer}/protocol/openid-connect/token",
        "backendRefs": [
            {"name": "keycloak", "namespace": "auth", "port": 8080}
        ],
    }
    assert oidc["clientID"] == "aiops-gateway"
    assert oidc["clientSecret"] == {"name": "aiops-gateway-oidc"}
    assert (
        oidc["redirectURL"] == "https://sso.127.0.0.1.nip.io/oauth2/callback"
    )
    assert oidc["logoutPath"] == "/oauth2/logout"
    assert oidc["cookieDomain"] == "127.0.0.1.nip.io"
    assert oidc["forwardAccessToken"] is True
    assert oidc["refreshToken"] is True
    assert oidc["scopes"] == ["openid", "profile", "email"]
    assert body["spec"]["extAuth"] == {
        "headersToExtAuth": ["authorization", "cookie"],
        "http": {
            "backendRefs": [
                {
                    "name": "aiops-backend",
                    "namespace": "ai-stack",
                    "port": 8000,
                }
            ],
            "path": "/v1alpha1/authz/route",
            "headersToBackend": [
                "x-auth-user-email",
                "x-auth-user-sub",
                "x-auth-org",
            ],
        },
        "failOpen": False,
    }
    assert "apiKeyAuth" not in body["spec"]


def test_ensure_security_policy_apikey_body(gateway_env):
    api_instance = _api()
    gateway.ensure_security_policy(
        "ai-stack",
        "qdrant-abc-api",
        "qdrant-abc-api",
        "apikey",
        "vdb-00000001-api.127.0.0.1.nip.io",
        secret_name="vdb-00000001-apikey-auth",
        api_instance=api_instance,
    )
    args, _ = api_instance.create_namespaced_custom_object.call_args
    body = args[4]
    assert body["spec"]["targetRefs"] == [_ref("qdrant-abc-api")]
    assert body["spec"]["apiKeyAuth"] == {
        "credentialRefs": [
            {"kind": "Secret", "name": "vdb-00000001-apikey-auth"}
        ],
        "extractFrom": [{"headers": ["x-api-key", "api-key"]}],
        "forwardClientIDHeader": "x-client-id",
        # The workload validates the same key (Task 13), so the gateway
        # must forward it.
        "sanitize": False,
    }
    assert "oidc" not in body["spec"]
    assert "extAuth" not in body["spec"]


def test_ensure_security_policy_apikey_requires_secret_name(gateway_env):
    with pytest.raises(ValueError):
        gateway.ensure_security_policy(
            "ai-stack", "p", "r", "apikey", "h", api_instance=_api()
        )


def test_ensure_security_policy_patches_when_present(gateway_env):
    api_instance = _api(get={"metadata": {"name": "p"}})
    gateway.ensure_security_policy(
        "ai-stack",
        "p",
        "r",
        "apikey",
        "h",
        secret_name="s",
        api_instance=api_instance,
    )
    api_instance.create_namespaced_custom_object.assert_not_called()
    args, _ = api_instance.patch_namespaced_custom_object.call_args
    assert args[:5] == (*SP, "p")
    assert args[5]["spec"]["targetRefs"] == [_ref("r")]


def test_delete_security_policy(gateway_env):
    api_instance = _api()
    gateway.delete_security_policy("ai-stack", "p", api_instance=api_instance)
    api_instance.delete_namespaced_custom_object.assert_called_once_with(
        *SP, "p"
    )
    api_instance.delete_namespaced_custom_object.side_effect = ApiException(
        status=404
    )
    gateway.delete_security_policy("ai-stack", "p", api_instance=api_instance)


def test_delete_security_policy_no_op_without_settings():
    api_instance = _api()
    gateway.delete_security_policy("ai-stack", "p", api_instance=api_instance)
    api_instance.delete_namespaced_custom_object.assert_not_called()


def test_ensure_backend_traffic_policy_body(gateway_env):
    api_instance = _api()
    gateway.ensure_backend_traffic_policy(
        "ai-stack", "nb-release", api_instance=api_instance
    )
    args, _ = api_instance.create_namespaced_custom_object.call_args
    assert args[:4] == BTP
    body = args[4]
    assert body["kind"] == "BackendTrafficPolicy"
    assert body["metadata"]["name"] == "nb-release"
    assert body["metadata"]["labels"] == {
        "app.kubernetes.io/managed-by": "aiops"
    }
    assert body["spec"] == {
        "targetRefs": [_ref("nb-release")],
        "timeout": {
            "http": {"requestTimeout": "0s", "streamIdleTimeout": "1h"}
        },
    }


def test_ensure_backend_traffic_policy_no_op_without_settings():
    api_instance = _api()
    gateway.ensure_backend_traffic_policy(
        "ai-stack", "nb-release", api_instance=api_instance
    )
    api_instance.create_namespaced_custom_object.assert_not_called()


def test_delete_backend_traffic_policy(gateway_env):
    api_instance = _api()
    gateway.delete_backend_traffic_policy(
        "ai-stack", "nb-release", api_instance=api_instance
    )
    api_instance.delete_namespaced_custom_object.assert_called_once_with(
        *BTP, "nb-release"
    )


def _shared_policy(*routes, rv="7"):
    return {
        "metadata": {"name": "aiops-workloads-oidc", "resourceVersion": rv},
        "spec": {"targetRefs": [_ref(r) for r in routes]},
    }


def _api_without_policy(namespace, *, sso_route=True):
    """Every object is missing (404) except, when sso_route, the ``sso``
    HTTPRoute of ``namespace``."""
    api_instance = _api()

    def get(group, version, ns, plural, name):
        if sso_route and plural == "httproutes" and name == "sso":
            assert ns == namespace
            return {"metadata": {"name": "sso"}}
        raise ApiException(status=404)

    api_instance.get_namespaced_custom_object.side_effect = get
    return api_instance


def test_add_oidc_target_creates_shared_policy_when_missing(gateway_env):
    api_instance = _api_without_policy("ai-stack")
    gateway.add_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    args, _ = api_instance.create_namespaced_custom_object.call_args
    assert args[:4] == SP
    body = args[4]
    assert body["metadata"]["name"] == "aiops-workloads-oidc"
    assert body["spec"]["targetRefs"] == [_ref("sso"), _ref("qdrant-abc")]
    assert (
        body["spec"]["oidc"]["redirectURL"]
        == "https://sso.127.0.0.1.nip.io/oauth2/callback"
    )
    api_instance.patch_namespaced_custom_object.assert_not_called()


def test_add_oidc_target_appends_with_resource_version(gateway_env):
    api_instance = _api(get=_shared_policy("sso", "other"))
    gateway.add_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.create_namespaced_custom_object.assert_not_called()
    args, _ = api_instance.patch_namespaced_custom_object.call_args
    assert args[:5] == (*SP, "aiops-workloads-oidc")
    assert args[5] == {
        "metadata": {"resourceVersion": "7"},
        "spec": {
            "targetRefs": [_ref("sso"), _ref("other"), _ref("qdrant-abc")]
        },
    }


def test_add_oidc_target_is_idempotent(gateway_env):
    api_instance = _api(get=_shared_policy("sso", "qdrant-abc"))
    gateway.add_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.patch_namespaced_custom_object.assert_not_called()


def test_add_oidc_target_retries_on_conflict(gateway_env):
    api_instance = _api(get=_shared_policy("sso"))
    api_instance.patch_namespaced_custom_object.side_effect = [
        ApiException(status=409),
        {},
    ]
    gateway.add_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    assert api_instance.patch_namespaced_custom_object.call_count == 2
    assert api_instance.get_namespaced_custom_object.call_count == 2


def test_add_oidc_target_gives_up_after_five_conflicts(gateway_env):
    api_instance = _api(get=_shared_policy("sso"))
    api_instance.patch_namespaced_custom_object.side_effect = ApiException(
        status=409
    )
    with pytest.raises(ApiException):
        gateway.add_oidc_target(
            "ai-stack", "qdrant-abc", api_instance=api_instance
        )
    assert api_instance.patch_namespaced_custom_object.call_count == 5


def test_add_oidc_target_raises_without_policy_or_sso_route(gateway_env):
    """No policy and no callback route in the namespace: nothing could
    ever complete a login there, so the route must not stay exposed."""
    api_instance = _api_without_policy("tenant-a", sso_route=False)
    with pytest.raises(gateway.OidcPolicyError) as excinfo:
        gateway.add_oidc_target(
            "tenant-a", "qdrant-abc", api_instance=api_instance
        )
    assert "tenant-a/aiops-workloads-oidc" in str(excinfo.value)
    api_instance.create_namespaced_custom_object.assert_not_called()
    api_instance.patch_namespaced_custom_object.assert_not_called()


def test_add_oidc_target_patches_the_policy_of_the_routes_namespace(
    gateway_env,
):
    """The chart renders the policy in its release namespace; the route
    there joins that policy, not the one in ai-stack."""
    api_instance = _api(get=_shared_policy("sso"))
    gateway.add_oidc_target(
        "tenant-a", "qdrant-abc", api_instance=api_instance
    )
    api_instance.get_namespaced_custom_object.assert_called_once_with(
        "gateway.envoyproxy.io",
        "v1alpha1",
        "tenant-a",
        "securitypolicies",
        "aiops-workloads-oidc",
    )
    args, _ = api_instance.patch_namespaced_custom_object.call_args
    assert args[:5] == (
        "gateway.envoyproxy.io",
        "v1alpha1",
        "tenant-a",
        "securitypolicies",
        "aiops-workloads-oidc",
    )
    assert args[5]["spec"]["targetRefs"] == [_ref("sso"), _ref("qdrant-abc")]


def test_add_oidc_target_raises_when_the_patch_fails(gateway_env):
    api_instance = _api(get=_shared_policy("sso"))
    api_instance.patch_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    with pytest.raises(ApiException):
        gateway.add_oidc_target(
            "ai-stack", "qdrant-abc", api_instance=api_instance
        )
    api_instance.patch_namespaced_custom_object.assert_called_once()


def test_add_oidc_target_raises_when_the_read_fails(gateway_env):
    api_instance = _api()
    api_instance.get_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    with pytest.raises(ApiException):
        gateway.add_oidc_target(
            "ai-stack", "qdrant-abc", api_instance=api_instance
        )
    api_instance.create_namespaced_custom_object.assert_not_called()


def test_add_oidc_target_no_op_without_settings():
    api_instance = _api()
    gateway.add_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.get_namespaced_custom_object.assert_not_called()


def test_protect_browser_route_attaches(gateway_env):
    api_instance = _api(get=_shared_policy("sso"))
    gateway.protect_browser_route(
        "tenant-a", "qdrant-abc", api_instance=api_instance
    )
    args, _ = api_instance.patch_namespaced_custom_object.call_args
    assert args[2] == "tenant-a"
    assert args[5]["spec"]["targetRefs"] == [_ref("sso"), _ref("qdrant-abc")]
    api_instance.delete_namespaced_custom_object.assert_not_called()


def test_protect_browser_route_deletes_the_route_and_raises(gateway_env):
    api_instance = _api(get=_shared_policy("sso"))
    api_instance.patch_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    with pytest.raises(gateway.OidcPolicyError) as excinfo:
        gateway.protect_browser_route(
            "tenant-a", "qdrant-abc", api_instance=api_instance
        )
    assert "aiops-workloads-oidc" in str(excinfo.value)
    assert "tenant-a/qdrant-abc" in str(excinfo.value)
    api_instance.delete_namespaced_custom_object.assert_called_once_with(
        "gateway.networking.k8s.io",
        "v1",
        "tenant-a",
        "httproutes",
        "qdrant-abc",
    )


def test_protect_browser_route_raises_even_when_the_delete_fails(
    gateway_env,
):
    api_instance = _api_without_policy("tenant-a", sso_route=False)
    api_instance.delete_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    with pytest.raises(gateway.OidcPolicyError):
        gateway.protect_browser_route(
            "tenant-a", "qdrant-abc", api_instance=api_instance
        )
    api_instance.delete_namespaced_custom_object.assert_called_once()


def test_protect_browser_route_no_op_without_settings():
    api_instance = _api()
    gateway.protect_browser_route(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.get_namespaced_custom_object.assert_not_called()


def test_remove_oidc_target(gateway_env):
    api_instance = _api(get=_shared_policy("sso", "qdrant-abc", "other"))
    gateway.remove_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    args, _ = api_instance.patch_namespaced_custom_object.call_args
    assert args[5] == {
        "metadata": {"resourceVersion": "7"},
        "spec": {"targetRefs": [_ref("sso"), _ref("other")]},
    }


def test_remove_oidc_target_in_any_namespace(gateway_env):
    api_instance = _api(get=_shared_policy("sso", "qdrant-abc"))
    gateway.remove_oidc_target(
        "tenant-a", "qdrant-abc", api_instance=api_instance
    )
    args, _ = api_instance.patch_namespaced_custom_object.call_args
    assert args[2] == "tenant-a"
    assert args[5]["spec"]["targetRefs"] == [_ref("sso")]


def test_remove_oidc_target_absent_or_missing_policy(gateway_env):
    api_instance = _api(get=_shared_policy("sso", "other"))
    gateway.remove_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.patch_namespaced_custom_object.assert_not_called()
    api_instance = _api()  # 404
    gateway.remove_oidc_target(
        "ai-stack", "qdrant-abc", api_instance=api_instance
    )
    api_instance.patch_namespaced_custom_object.assert_not_called()


def _grant(*namespaces):
    return {
        "metadata": {"name": "g"},
        "spec": {
            "from": [
                {
                    "group": "gateway.envoyproxy.io",
                    "kind": "SecurityPolicy",
                    "namespace": ns,
                }
                for ns in namespaces
            ],
            "to": [{"group": "", "kind": "Service"}],
        },
    }


def test_ensure_reference_grant_patches_both_grants(gateway_env):
    api_instance = _api(get=_grant("ai-stack"))
    gateway.ensure_reference_grant("team-a", api_instance=api_instance)
    calls = api_instance.patch_namespaced_custom_object.call_args_list
    assert [(c.args[2], c.args[4]) for c in calls] == [
        ("auth", "allow-ai-stack-securitypolicy-to-keycloak"),
        ("ai-stack", "allow-securitypolicy-to-aiops-backend"),
    ]
    for c in calls:
        assert c.args[:2] == ("gateway.networking.k8s.io", "v1beta1")
        assert c.args[3] == "referencegrants"
        assert c.args[5] == {
            "spec": {
                "from": [
                    {
                        "group": "gateway.envoyproxy.io",
                        "kind": "SecurityPolicy",
                        "namespace": "ai-stack",
                    },
                    {
                        "group": "gateway.envoyproxy.io",
                        "kind": "SecurityPolicy",
                        "namespace": "team-a",
                    },
                ]
            }
        }


def test_ensure_reference_grant_is_idempotent(gateway_env):
    api_instance = _api(get=_grant("ai-stack", "team-a"))
    gateway.ensure_reference_grant("team-a", api_instance=api_instance)
    api_instance.patch_namespaced_custom_object.assert_not_called()


def test_ensure_reference_grant_no_op_without_settings():
    api_instance = _api()
    gateway.ensure_reference_grant("team-a", api_instance=api_instance)
    api_instance.get_namespaced_custom_object.assert_not_called()


def test_ensure_gateway_client_secret_copies(gateway_env):
    core = mock.Mock(spec=client.CoreV1Api)
    source = client.V1Secret(
        metadata=client.V1ObjectMeta(
            name="aiops-gateway-oidc", namespace="ai-stack"
        ),
        type="Opaque",
        data={"client-secret": "ZGV2"},
    )
    core.read_namespaced_secret.side_effect = [
        ApiException(status=404),
        source,
    ]
    gateway.ensure_gateway_client_secret("team-a", core_v1_api=core)
    # The target is checked first: under the chart the Secret is already
    # in the release namespace and there is no ai-stack source to read.
    assert core.read_namespaced_secret.call_args_list == [
        mock.call("aiops-gateway-oidc", "team-a"),
        mock.call("aiops-gateway-oidc", "ai-stack"),
    ]
    core.create_namespaced_secret.assert_called_once()
    ns, body = core.create_namespaced_secret.call_args.args
    assert ns == "team-a"
    assert body.metadata.name == "aiops-gateway-oidc"
    assert body.metadata.namespace == "team-a"
    assert body.metadata.labels == {"app.kubernetes.io/managed-by": "aiops"}
    assert body.data == {"client-secret": "ZGV2"}
    assert body.type == "Opaque"


def test_ensure_gateway_client_secret_skips_source_namespace_and_existing(
    gateway_env,
):
    core = mock.Mock(spec=client.CoreV1Api)
    gateway.ensure_gateway_client_secret("ai-stack", core_v1_api=core)
    core.read_namespaced_secret.assert_not_called()
    core.read_namespaced_secret.return_value = client.V1Secret()
    gateway.ensure_gateway_client_secret("team-a", core_v1_api=core)
    core.read_namespaced_secret.assert_called_once_with(
        "aiops-gateway-oidc", "team-a"
    )
    core.create_namespaced_secret.assert_not_called()


def test_secret_exists(gateway_env):
    core = mock.Mock(spec=client.CoreV1Api)
    assert gateway.secret_exists("ai-stack", "s", core_v1_api=core) is True
    core.read_namespaced_secret.side_effect = ApiException(status=404)
    assert gateway.secret_exists("ai-stack", "s", core_v1_api=core) is False
    core.read_namespaced_secret.side_effect = ApiException(status=500)
    with pytest.raises(ApiException):
        gateway.secret_exists("ai-stack", "s", core_v1_api=core)


def _core_with_secret(exists: bool):
    """A CoreV1Api mock whose read_namespaced_secret finds the Secret or
    404s, which is what gateway.secret_exists turns into True/False."""
    core = mock.Mock(spec=client.CoreV1Api)
    if not exists:
        core.read_namespaced_secret.side_effect = ApiException(status=404)
    return core


def test_protect_sdk_route_creates_the_policy_when_the_secret_is_there(
    gateway_env,
):
    api = _api()
    core = _core_with_secret(True)

    gateway.protect_sdk_route(
        "ai-stack",
        "vdb-1-api",
        "vdb-1-api-apikey",
        "vdb-1-apikey-auth",
        api_instance=api,
        core_v1_api=core,
    )

    body = (
        api.create_namespaced_custom_object.call_args.kwargs.get("body")
        or api.create_namespaced_custom_object.call_args.args[4]
    )
    assert body["metadata"]["name"] == "vdb-1-api-apikey"
    assert "apiKeyAuth" in body["spec"]
    api.delete_namespaced_custom_object.assert_not_called()


def test_protect_sdk_route_deletes_the_route_when_the_secret_is_missing(
    gateway_env,
):
    """The lenient behaviour this replaced (skip the policy, keep the
    route) is the exposure #27 closes: the host would be served with
    nothing checking the key."""
    api = _api()
    core = _core_with_secret(False)

    with pytest.raises(gateway.ApiKeyPolicyError) as excinfo:
        gateway.protect_sdk_route(
            "ai-stack",
            "vdb-1-api",
            "vdb-1-api-apikey",
            "vdb-1-apikey-auth",
            api_instance=api,
            core_v1_api=core,
        )

    assert "vdb-1-apikey-auth" in str(excinfo.value)
    assert isinstance(excinfo.value, gateway.GatewayPolicyError)
    deleted = api.delete_namespaced_custom_object.call_args.args
    assert deleted[3] == "httproutes"
    assert deleted[4] == "vdb-1-api"


def test_protect_sdk_route_deletes_the_route_when_the_policy_fails(
    gateway_env,
):
    api = mock.Mock()
    api.create_namespaced_custom_object.side_effect = ApiException(status=500)
    api.get_namespaced_custom_object.side_effect = ApiException(status=404)
    core = _core_with_secret(True)

    with pytest.raises(gateway.ApiKeyPolicyError):
        gateway.protect_sdk_route(
            "ai-stack",
            "inf-1",
            "inf-1",
            "inf-1-apikey-auth",
            api_instance=api,
            core_v1_api=core,
        )

    deleted = api.delete_namespaced_custom_object.call_args.args
    assert (deleted[3], deleted[4]) == ("httproutes", "inf-1")


def test_protect_sdk_route_still_raises_when_the_cleanup_delete_fails(
    gateway_env,
):
    """The route delete is best effort, but the error is not: if the
    cleanup cannot run, the caller must still fail so the install does
    not report success over a route that may still be published."""
    api = _api()
    api.create_namespaced_custom_object.side_effect = ApiException(status=500)
    api.get_namespaced_custom_object.side_effect = ApiException(status=404)
    api.delete_namespaced_custom_object.side_effect = ApiException(status=500)
    core = _core_with_secret(True)

    with pytest.raises(gateway.ApiKeyPolicyError):
        gateway.protect_sdk_route(
            "ai-stack",
            "inf-1",
            "inf-1",
            "inf-1-apikey-auth",
            api_instance=api,
            core_v1_api=core,
        )

    api.delete_namespaced_custom_object.assert_called()


def test_protect_sdk_route_keeps_a_route_the_policy_already_covers(
    gateway_env,
):
    """A blip re-applying a policy that is already correct must not take
    a running workload off the air: on the second and later upgrades the
    route and its policy already exist, so the only safe answer to "I
    could not re-confirm it" is to leave the route alone and still fail.
    """
    api = _api(get={"spec": {"targetRefs": [{"name": "inf-1"}]}})
    api.patch_namespaced_custom_object.side_effect = ApiException(status=500)
    api.create_namespaced_custom_object.side_effect = ApiException(status=500)
    core = _core_with_secret(True)

    with pytest.raises(gateway.ApiKeyPolicyError):
        gateway.protect_sdk_route(
            "ai-stack",
            "inf-1",
            "inf-1",
            "inf-1-apikey-auth",
            api_instance=api,
            core_v1_api=core,
        )

    api.delete_namespaced_custom_object.assert_not_called()


def test_protect_browser_route_does_not_repatch_a_route_already_listed(
    gateway_env,
):
    """The browser path gets the same property for free: a route already
    in targetRefs needs no patch, so a re-run cannot fail and cannot
    take the route down. The SDK path needs the explicit guard above
    because its policy is always re-applied."""
    api = _api(
        get={"spec": {"targetRefs": [{"name": "sso"}, {"name": "vdb-1"}]}}
    )

    gateway.protect_browser_route("ai-stack", "vdb-1", api_instance=api)

    api.patch_namespaced_custom_object.assert_not_called()
    api.delete_namespaced_custom_object.assert_not_called()


def test_protect_sdk_route_is_a_noop_without_gateway_settings(monkeypatch):
    monkeypatch.delenv("AIOPS_PARENT_DOMAIN", raising=False)
    api = mock.Mock()

    gateway.protect_sdk_route(
        "ai-stack", "inf-1", "inf-1", "s", api_instance=api
    )

    api.create_namespaced_custom_object.assert_not_called()
    api.delete_namespaced_custom_object.assert_not_called()


@pytest.mark.parametrize(
    ("timeouts", "expected"),
    [
        (None, {"http": {"requestTimeout": "0s", "streamIdleTimeout": "1h"}}),
        (
            gateway.INFERENCE_TIMEOUTS,
            {"http": {"requestTimeout": "0s", "streamIdleTimeout": "10m"}},
        ),
    ],
)
def test_ensure_backend_traffic_policy_timeouts(
    gateway_env, timeouts, expected
):
    api_instance = _api()
    gateway.ensure_backend_traffic_policy(
        "ai-stack",
        "ollama-abcdef12",
        api_instance=api_instance,
        timeouts=timeouts,
    )
    args, _ = api_instance.create_namespaced_custom_object.call_args
    assert args[4]["spec"]["timeout"] == expected
