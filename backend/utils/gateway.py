"""Gateway hostnames, URLs, HTTPRoutes and policies for deployed instances.

Every function here is a no-op (returns None, or does nothing) when
AIOPS_PARENT_DOMAIN is unset, so the stack behaves exactly as it did before
the gateway existed unless the T1 env contract is present. See
docs/superpowers/plans/2026-09-04-authentication.md, Tasks 2 and 10.

Browser hosts (``nb-<id8>``, ``vdb-<id8>``) are protected by ONE shared
OIDC ``SecurityPolicy`` per namespace, ``aiops-workloads-oidc``, whose
``targetRefs`` list the controllers maintain (``add_oidc_target`` /
``remove_oidc_target``). One policy, not one per instance: Envoy Gateway
derives the OIDC cookie suffix from the policy, so only the policy that
started a login can finish it on the shared callback host
``sso.<parent domain>`` (Task 10 spike, gateway notes "Spike results").
SDK hosts (``vdb-<id8>-api``, ``inf-<id8>``) get one API-key policy each,
created only once the credential Secret from Task 12 exists.
"""

import os
import uuid
from dataclasses import dataclass
from typing import Literal

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from auth.settings import auth_settings
from logger import setup_logger

logger = setup_logger(__name__)

HTTPROUTE_GROUP = "gateway.networking.k8s.io"
HTTPROUTE_VERSION = "v1"
HTTPROUTE_PLURAL = "httproutes"

POLICY_GROUP = "gateway.envoyproxy.io"
POLICY_VERSION = "v1alpha1"
SECURITYPOLICY_PLURAL = "securitypolicies"
BACKENDTRAFFICPOLICY_PLURAL = "backendtrafficpolicies"

REFERENCEGRANT_GROUP = "gateway.networking.k8s.io"
REFERENCEGRANT_VERSION = "v1beta1"
REFERENCEGRANT_PLURAL = "referencegrants"

MANAGED_BY_LABEL = {"app.kubernetes.io/managed-by": "aiops"}

# The namespace that hosts the shared callback route "sso"
# (infra/local/gateway/sso.yaml) and therefore the only namespace whose
# shared OIDC policy can complete a login; see add_oidc_target.
SHARED_OIDC_NAMESPACE = "ai-stack"
SHARED_OIDC_POLICY_NAME = "aiops-workloads-oidc"
SSO_ROUTE_NAME = "sso"
OIDC_CALLBACK_PATH = "/oauth2/callback"
OIDC_LOGOUT_PATH = "/oauth2/logout"
OIDC_SCOPES = ["openid", "profile", "email"]

# In-cluster Keycloak (infra/local/auth/keycloak.yaml): the OIDC filter
# exchanges codes and fetches keys over plain HTTP through this Service.
KEYCLOAK_BACKEND_REF = {"name": "keycloak", "namespace": "auth", "port": 8080}
GATEWAY_CLIENT_ID = "aiops-gateway"
GATEWAY_CLIENT_SECRET_NAME = "aiops-gateway-oidc"
GATEWAY_CLIENT_SECRET_NAMESPACE = "ai-stack"

# The ext-authz backend: this API, reached through the selector-less
# Service in infra/local/gateway/backend-host-service.yaml.
AUTHZ_BACKEND_REF = {
    "name": "aiops-backend",
    "namespace": "ai-stack",
    "port": 8000,
}
AUTHZ_PATH = "/v1alpha1/authz/route"
AUTHZ_HEADERS_TO_BACKEND = [
    "x-auth-user-email",
    "x-auth-user-sub",
    "x-auth-org",
]

# API keys travel in either header; the client id (the Secret key, the
# instance id) is forwarded to the workload as x-client-id. The key
# itself is forwarded too (sanitize false): the workload is configured
# with the same value (Task 13, the Qdrant apiKey) and validates it again.
APIKEY_HEADERS = ["x-api-key", "api-key"]
APIKEY_CLIENT_ID_HEADER = "x-client-id"

# The ReferenceGrants that let a SecurityPolicy in another namespace
# reach the keycloak and aiops-backend Services: (namespace, name).
REFERENCE_GRANTS = (
    ("auth", "allow-ai-stack-securitypolicy-to-keycloak"),
    ("ai-stack", "allow-securitypolicy-to-aiops-backend"),
)

# Kernel WebSockets stay open for hours; the Envoy default idle timeout is
# five minutes (gateway notes section 7).
WEBSOCKET_TIMEOUTS = {
    "http": {"requestTimeout": "0s", "streamIdleTimeout": "1h"}
}

OIDC_CONFLICT_RETRIES = 5


@dataclass(frozen=True)
class GatewaySettings:
    parent_domain: str
    gateway_name: str
    gateway_namespace: str


def gateway_settings() -> GatewaySettings | None:
    """Read the T1 env contract; None when the gateway is not configured."""
    parent_domain = os.environ.get("AIOPS_PARENT_DOMAIN")
    if not parent_domain:
        return None
    return GatewaySettings(
        parent_domain=parent_domain,
        gateway_name=os.environ.get("AIOPS_GATEWAY_NAME", "aiops"),
        gateway_namespace=os.environ.get(
            "AIOPS_GATEWAY_NAMESPACE", "envoy-gateway-system"
        ),
    )


def id8(instance_id: uuid.UUID) -> str:
    """The last eight hex characters of the id, used in every hostname.

    Under TEST_MODE (utils/genid.py) the deterministic ids all start with
    "00000000", so the *last* eight characters (not the first, which the
    Helm release names already use) are what makes hostnames unique.
    """
    return instance_id.hex[-8:]


def instance_hostname(
    kind: str, instance_id: uuid.UUID, suffix: str = ""
) -> str | None:
    """Hostname for a deployed instance, or None without gateway settings."""
    settings = gateway_settings()
    if settings is None:
        return None
    return f"{kind}-{id8(instance_id)}{suffix}.{settings.parent_domain}"


def instance_url(
    kind: str, instance_id: uuid.UUID, path: str = "/", suffix: str = ""
) -> str | None:
    """Full gateway URL for a deployed instance, or None when disabled."""
    hostname = instance_hostname(kind, instance_id, suffix)
    if hostname is None:
        return None
    return f"https://{hostname}{path}"


def sso_hostname() -> str | None:
    """The shared OIDC callback host, or None without gateway settings."""
    settings = gateway_settings()
    if settings is None:
        return None
    return f"{SSO_ROUTE_NAME}.{settings.parent_domain}"


def oidc_redirect_url() -> str | None:
    """The one redirect URI registered on the aiops-gateway client."""
    hostname = sso_hostname()
    if hostname is None:
        return None
    return f"https://{hostname}{OIDC_CALLBACK_PATH}"


def oidc_issuer() -> str:
    """The realm issuer: OIDC_ISSUER, else Keycloak on the parent domain."""
    issuer = auth_settings().issuer
    if issuer:
        return issuer
    settings = gateway_settings()
    domain = settings.parent_domain if settings else "127.0.0.1.nip.io"
    return f"https://auth.{domain}/realms/aiops"


def apikey_secret_name(kind: str, instance_id: uuid.UUID) -> str:
    """The Secret Task 12 writes for the gateway's apiKeyAuth."""
    return f"{kind}-{id8(instance_id)}-apikey-auth"


def _ensure_custom_object(
    api_instance: client.CustomObjectsApi,
    group: str,
    version: str,
    namespace: str,
    plural: str,
    name: str,
    body: dict,
) -> None:
    """Create the object, or patch it (merge patch) when it exists."""
    try:
        api_instance.get_namespaced_custom_object(
            group, version, namespace, plural, name
        )
    except ApiException as e:
        if e.status != 404:
            raise
        api_instance.create_namespaced_custom_object(
            group, version, namespace, plural, body
        )
        logger.info("Created %s %s/%s", body["kind"], namespace, name)
        return
    api_instance.patch_namespaced_custom_object(
        group, version, namespace, plural, name, body
    )
    logger.info("Patched %s %s/%s", body["kind"], namespace, name)


def _delete_custom_object(
    api_instance: client.CustomObjectsApi,
    group: str,
    version: str,
    namespace: str,
    plural: str,
    name: str,
) -> None:
    """Delete the object; a missing one is not an error."""
    try:
        api_instance.delete_namespaced_custom_object(
            group, version, namespace, plural, name
        )
        logger.info("Deleted %s %s/%s", plural, namespace, name)
    except ApiException as e:
        if e.status != 404:
            raise


def _http_route_body(
    name: str,
    namespace: str,
    hostname: str,
    service_name: str,
    port: int,
    settings: GatewaySettings,
) -> dict:
    return {
        "apiVersion": f"{HTTPROUTE_GROUP}/{HTTPROUTE_VERSION}",
        "kind": "HTTPRoute",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": dict(MANAGED_BY_LABEL),
        },
        "spec": {
            "parentRefs": [
                {
                    "name": settings.gateway_name,
                    "namespace": settings.gateway_namespace,
                }
            ],
            "hostnames": [hostname],
            "rules": [{"backendRefs": [{"name": service_name, "port": port}]}],
        },
    }


def ensure_http_route(
    namespace: str,
    name: str,
    hostname: str,
    service_name: str,
    port: int,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Create or patch the HTTPRoute for one instance.

    No-op without gateway settings. Route names come from the caller (the
    Helm release name, and "<release>-api" for the SDK host); this function
    only builds and applies the body.
    """
    settings = gateway_settings()
    if settings is None:
        return
    api_instance = api_instance or client.CustomObjectsApi()
    body = _http_route_body(
        name, namespace, hostname, service_name, port, settings
    )
    _ensure_custom_object(
        api_instance,
        HTTPROUTE_GROUP,
        HTTPROUTE_VERSION,
        namespace,
        HTTPROUTE_PLURAL,
        name,
        body,
    )


def delete_http_route(
    namespace: str,
    name: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Delete the HTTPRoute; a no-op without gateway settings, ignores 404."""
    if gateway_settings() is None:
        return
    api_instance = api_instance or client.CustomObjectsApi()
    _delete_custom_object(
        api_instance,
        HTTPROUTE_GROUP,
        HTTPROUTE_VERSION,
        namespace,
        HTTPROUTE_PLURAL,
        name,
    )


# --- SecurityPolicy and BackendTrafficPolicy (Task 10) ---------------------


def _route_ref(route_name: str) -> dict:
    return {"group": HTTPROUTE_GROUP, "kind": "HTTPRoute", "name": route_name}


def _policy_metadata(name: str, namespace: str) -> dict:
    return {
        "name": name,
        "namespace": namespace,
        "labels": dict(MANAGED_BY_LABEL),
    }


def _oidc_spec(callback_hostname: str) -> dict:
    """The OIDC + ext-authz half of a SecurityPolicy spec.

    ``callback_hostname`` is where Keycloak sends the browser back to; it
    is the shared ``sso`` host, never the instance host (module docstring).
    """
    issuer = oidc_issuer()
    settings = gateway_settings()
    return {
        "oidc": {
            "provider": {
                "issuer": issuer,
                "authorizationEndpoint": f"{issuer}/protocol/openid-connect/auth",
                "tokenEndpoint": f"{issuer}/protocol/openid-connect/token",
                "backendRefs": [dict(KEYCLOAK_BACKEND_REF)],
            },
            "clientID": GATEWAY_CLIENT_ID,
            "clientSecret": {"name": GATEWAY_CLIENT_SECRET_NAME},
            "redirectURL": f"https://{callback_hostname}{OIDC_CALLBACK_PATH}",
            "logoutPath": OIDC_LOGOUT_PATH,
            "cookieDomain": settings.parent_domain,
            "forwardAccessToken": True,
            "refreshToken": True,
            "scopes": list(OIDC_SCOPES),
        },
        "extAuth": {
            "headersToExtAuth": ["authorization", "cookie"],
            "http": {
                "backendRefs": [dict(AUTHZ_BACKEND_REF)],
                "path": AUTHZ_PATH,
                "headersToBackend": list(AUTHZ_HEADERS_TO_BACKEND),
            },
            "failOpen": False,
        },
    }


def _apikey_spec(secret_name: str) -> dict:
    return {
        "apiKeyAuth": {
            "credentialRefs": [{"kind": "Secret", "name": secret_name}],
            "extractFrom": [{"headers": list(APIKEY_HEADERS)}],
            "forwardClientIDHeader": APIKEY_CLIENT_ID_HEADER,
            "sanitize": False,
        }
    }


def _security_policy_body(
    namespace: str,
    name: str,
    route_names: list[str],
    mode: Literal["oidc", "apikey"],
    hostname: str,
    secret_name: str | None,
) -> dict:
    if mode == "oidc":
        spec = _oidc_spec(hostname)
    elif mode == "apikey":
        if not secret_name:
            raise ValueError("an apikey SecurityPolicy needs secret_name")
        spec = _apikey_spec(secret_name)
    else:
        raise ValueError(f"unknown SecurityPolicy mode {mode!r}")
    return {
        "apiVersion": f"{POLICY_GROUP}/{POLICY_VERSION}",
        "kind": "SecurityPolicy",
        "metadata": _policy_metadata(name, namespace),
        "spec": {
            "targetRefs": [_route_ref(r) for r in route_names],
            **spec,
        },
    }


def ensure_security_policy(
    namespace: str,
    name: str,
    route_name: str,
    mode: Literal["oidc", "apikey"],
    hostname: str,
    secret_name: str | None = None,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Create or patch a SecurityPolicy targeting one HTTPRoute.

    ``mode="oidc"``: OIDC against the realm plus ext-authz to this API;
    ``hostname`` is the callback host. ``mode="apikey"``: API-key auth from
    the credential Secret ``secret_name``. No-op without gateway settings.
    A patch replaces ``targetRefs``, so never use this on the shared OIDC
    policy after creation: use ``add_oidc_target`` instead.
    """
    if gateway_settings() is None:
        return
    body = _security_policy_body(
        namespace, name, [route_name], mode, hostname, secret_name
    )
    _ensure_custom_object(
        api_instance or client.CustomObjectsApi(),
        POLICY_GROUP,
        POLICY_VERSION,
        namespace,
        SECURITYPOLICY_PLURAL,
        name,
        body,
    )


def delete_security_policy(
    namespace: str,
    name: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Delete a SecurityPolicy; no-op without settings, ignores 404."""
    if gateway_settings() is None:
        return
    _delete_custom_object(
        api_instance or client.CustomObjectsApi(),
        POLICY_GROUP,
        POLICY_VERSION,
        namespace,
        SECURITYPOLICY_PLURAL,
        name,
    )


def ensure_backend_traffic_policy(
    namespace: str,
    route_name: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Give a WebSocket route (notebooks) long timeouts; named after it."""
    if gateway_settings() is None:
        return
    body = {
        "apiVersion": f"{POLICY_GROUP}/{POLICY_VERSION}",
        "kind": "BackendTrafficPolicy",
        "metadata": _policy_metadata(route_name, namespace),
        "spec": {
            "targetRefs": [_route_ref(route_name)],
            "timeout": {k: dict(v) for k, v in WEBSOCKET_TIMEOUTS.items()},
        },
    }
    _ensure_custom_object(
        api_instance or client.CustomObjectsApi(),
        POLICY_GROUP,
        POLICY_VERSION,
        namespace,
        BACKENDTRAFFICPOLICY_PLURAL,
        route_name,
        body,
    )


def delete_backend_traffic_policy(
    namespace: str,
    route_name: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    if gateway_settings() is None:
        return
    _delete_custom_object(
        api_instance or client.CustomObjectsApi(),
        POLICY_GROUP,
        POLICY_VERSION,
        namespace,
        BACKENDTRAFFICPOLICY_PLURAL,
        route_name,
    )


def _patch_oidc_targets(
    api_instance: client.CustomObjectsApi,
    namespace: str,
    route_name: str,
    add: bool,
) -> None:
    """Read-modify-write the shared policy's targetRefs.

    The patch carries the resourceVersion it read, so a concurrent change
    (another instance being created or deleted) is a 409 and the loop
    starts over from a fresh read, at most OIDC_CONFLICT_RETRIES times.
    """
    for attempt in range(1, OIDC_CONFLICT_RETRIES + 1):
        try:
            policy = api_instance.get_namespaced_custom_object(
                POLICY_GROUP,
                POLICY_VERSION,
                namespace,
                SECURITYPOLICY_PLURAL,
                SHARED_OIDC_POLICY_NAME,
            )
        except ApiException as e:
            if e.status != 404:
                raise
            if not add:
                return
            body = _security_policy_body(
                namespace,
                SHARED_OIDC_POLICY_NAME,
                [SSO_ROUTE_NAME, route_name],
                "oidc",
                sso_hostname(),
                None,
            )
            api_instance.create_namespaced_custom_object(
                POLICY_GROUP,
                POLICY_VERSION,
                namespace,
                SECURITYPOLICY_PLURAL,
                body,
            )
            logger.info(
                "Created SecurityPolicy %s/%s with target %s",
                namespace,
                SHARED_OIDC_POLICY_NAME,
                route_name,
            )
            return
        refs = list(policy.get("spec", {}).get("targetRefs") or [])
        present = any(r.get("name") == route_name for r in refs)
        if add == present:
            return
        if add:
            refs.append(_route_ref(route_name))
        else:
            refs = [r for r in refs if r.get("name") != route_name]
        patch = {
            "metadata": {
                "resourceVersion": policy["metadata"].get("resourceVersion")
            },
            "spec": {"targetRefs": refs},
        }
        try:
            api_instance.patch_namespaced_custom_object(
                POLICY_GROUP,
                POLICY_VERSION,
                namespace,
                SECURITYPOLICY_PLURAL,
                SHARED_OIDC_POLICY_NAME,
                patch,
            )
        except ApiException as e:
            if e.status != 409 or attempt == OIDC_CONFLICT_RETRIES:
                raise
            logger.info(
                "SecurityPolicy %s/%s changed underneath us, retrying (%d)",
                namespace,
                SHARED_OIDC_POLICY_NAME,
                attempt,
            )
            continue
        logger.info(
            "%s target %s on SecurityPolicy %s/%s",
            "Added" if add else "Removed",
            route_name,
            namespace,
            SHARED_OIDC_POLICY_NAME,
        )
        return


def add_oidc_target(
    namespace: str,
    route_name: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Put a browser route under the shared OIDC policy of its namespace.

    Creates the policy (with the ``sso`` callback route as its first
    target) when it is missing. Only SHARED_OIDC_NAMESPACE hosts the
    callback route, so a route anywhere else is left unprotected with a
    warning until per-namespace SSO exists (gateway notes).
    """
    if gateway_settings() is None:
        return
    if namespace != SHARED_OIDC_NAMESPACE:
        logger.warning(
            "No OIDC policy for HTTPRoute %s/%s: the shared callback route "
            "only exists in %s, so browser routes outside it stay "
            "unprotected",
            namespace,
            route_name,
            SHARED_OIDC_NAMESPACE,
        )
        return
    _patch_oidc_targets(
        api_instance or client.CustomObjectsApi(), namespace, route_name, True
    )


def remove_oidc_target(
    namespace: str,
    route_name: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Take a route out of the shared OIDC policy; the policy stays."""
    if gateway_settings() is None or namespace != SHARED_OIDC_NAMESPACE:
        return
    _patch_oidc_targets(
        api_instance or client.CustomObjectsApi(),
        namespace,
        route_name,
        False,
    )


# --- Cross-namespace plumbing ---------------------------------------------


def ensure_reference_grant(
    from_namespace: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
) -> None:
    """Let SecurityPolicies in ``from_namespace`` reach keycloak and the
    aiops-backend Service: add the namespace to both ReferenceGrants
    (REFERENCE_GRANTS) when it is not listed yet."""
    if gateway_settings() is None:
        return
    api_instance = api_instance or client.CustomObjectsApi()
    entry = {
        "group": POLICY_GROUP,
        "kind": "SecurityPolicy",
        "namespace": from_namespace,
    }
    for grant_namespace, grant_name in REFERENCE_GRANTS:
        grant = api_instance.get_namespaced_custom_object(
            REFERENCEGRANT_GROUP,
            REFERENCEGRANT_VERSION,
            grant_namespace,
            REFERENCEGRANT_PLURAL,
            grant_name,
        )
        sources = list(grant.get("spec", {}).get("from") or [])
        if any(s.get("namespace") == from_namespace for s in sources):
            continue
        sources.append(entry)
        api_instance.patch_namespaced_custom_object(
            REFERENCEGRANT_GROUP,
            REFERENCEGRANT_VERSION,
            grant_namespace,
            REFERENCEGRANT_PLURAL,
            grant_name,
            {"spec": {"from": sources}},
        )
        logger.info(
            "Added namespace %s to ReferenceGrant %s/%s",
            from_namespace,
            grant_namespace,
            grant_name,
        )


def ensure_gateway_client_secret(
    namespace: str,
    *,
    core_v1_api: client.CoreV1Api | None = None,
) -> None:
    """Copy the aiops-gateway-oidc Secret from ai-stack into ``namespace``
    (an OIDC policy can only reference a Secret in its own namespace)."""
    if (
        gateway_settings() is None
        or namespace == GATEWAY_CLIENT_SECRET_NAMESPACE
    ):
        return
    core_v1_api = core_v1_api or client.CoreV1Api()
    source = core_v1_api.read_namespaced_secret(
        GATEWAY_CLIENT_SECRET_NAME, GATEWAY_CLIENT_SECRET_NAMESPACE
    )
    if secret_exists(
        namespace, GATEWAY_CLIENT_SECRET_NAME, core_v1_api=core_v1_api
    ):
        return
    core_v1_api.create_namespaced_secret(
        namespace,
        client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=GATEWAY_CLIENT_SECRET_NAME,
                namespace=namespace,
                labels=dict(MANAGED_BY_LABEL),
            ),
            type=source.type,
            data=source.data,
        ),
    )
    logger.info(
        "Copied Secret %s into %s", GATEWAY_CLIENT_SECRET_NAME, namespace
    )


def secret_exists(
    namespace: str, name: str, *, core_v1_api: client.CoreV1Api | None = None
) -> bool:
    core_v1_api = core_v1_api or client.CoreV1Api()
    try:
        core_v1_api.read_namespaced_secret(name, namespace)
    except ApiException as e:
        if e.status == 404:
            return False
        raise
    return True


def ensure_apikey_policy(
    namespace: str,
    route_name: str,
    secret_name: str,
    *,
    api_instance: client.CustomObjectsApi | None = None,
    core_v1_api: client.CoreV1Api | None = None,
) -> bool:
    """API-key policy for an SDK route, but only once its credential
    Secret exists (Task 12 writes it); the policy is named after the
    route. Returns whether a policy was ensured."""
    if gateway_settings() is None:
        return False
    if not secret_exists(namespace, secret_name, core_v1_api=core_v1_api):
        logger.info(
            "No API-key policy for HTTPRoute %s/%s yet: Secret %s is missing",
            namespace,
            route_name,
            secret_name,
        )
        return False
    ensure_security_policy(
        namespace,
        route_name,
        route_name,
        "apikey",
        "",
        secret_name,
        api_instance=api_instance,
    )
    return True
