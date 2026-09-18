"""Langflow's API, called as the platform user, and what we put there.

Langflow runs on platform identity (ADR 0002): it verifies the Keycloak
token the gateway forwards and keeps one Langflow user per platform
user. So the backend never holds a Langflow credential of its own -- it
forwards the caller's bearer, and Langflow's API answers as that person.
Locally the calls go through the gateway host (passThroughAuthHeader
lets a bearer skip the OIDC redirect), where ext-authz and Langflow
both verify the token; in the chart, through the Service, where
Langflow does.

What we provision is Langflow's "OpenAI Compatible" provider (the
lfx_openai_compatible bundle, made for "vLLM, LiteLLM, ..."), pointed at
LiteLLM: OPENAI_COMPATIBLE_BASE_URL, the in-cluster address plus /v1,
and OPENAI_COMPATIBLE_API_KEY, a LiteLLM virtual key of the member's
own in the organization's team (utils.litellm.ensure_user_key). Langflow
checks the key by listing <base>/models with it and lists the same
route live in its Language Model and Embedding Model pickers, so a flow
picks inst-<id8> from a dropdown. The base URL goes first: the key's
check reads it. From then on that provider slot is platform-managed;
a sync rewrites it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from models.organization import Organization
from schemas.langflow import LangflowModelSchema, LangflowProvisionSchema
from utils.litellm import ensure_user_key

logger = logging.getLogger(__name__)

PROVIDER = "OpenAI Compatible"
BASE_URL_VAR = "OPENAI_COMPATIBLE_BASE_URL"
API_KEY_VAR = "OPENAI_COMPATIBLE_API_KEY"
# Langflow's component fields these variables pre-fill (the bundle's
# extension.json component_metadata.mapping_field).
BASE_URL_FIELDS = ["openai_compatible_base_url"]
API_KEY_FIELDS = ["api_key"]
TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class LangflowSettings:
    api_url: str
    litellm_cluster_url: str


def langflow_settings() -> LangflowSettings | None:
    """``LANGFLOW_API_URL`` (required) and the LiteLLM address a pod can
    reach (``LITELLM_CLUSTER_URL``, else the backend's own
    ``LITELLM_URL``); ``None`` without the first."""
    api_url = os.environ.get("LANGFLOW_API_URL", "").strip().rstrip("/")
    if not api_url:
        return None
    cluster = os.environ.get("LITELLM_CLUSTER_URL", "").strip()
    cluster = cluster or os.environ.get("LITELLM_URL", "").strip()
    return LangflowSettings(
        api_url=api_url, litellm_cluster_url=cluster.rstrip("/")
    )


class LangflowError(Exception):
    def __init__(self, detail: str, status: int | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status = status


class LangflowClient:
    def __init__(self, base_url: str, bearer: str, *, transport=None):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=TIMEOUT_SECONDS,
            transport=transport,
        )

    def __enter__(self) -> LangflowClient:
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise LangflowError(f"Langflow is unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise LangflowError(
                f"Langflow answered {response.status_code}: "
                f"{_detail(response)}",
                response.status_code,
            )
        return response.json()

    def whoami(self) -> dict:
        return self._request("GET", "/api/v1/users/whoami")

    def list_variables(self) -> list[dict]:
        # The trailing slash matters: without it Langflow answers 404.
        return self._request("GET", "/api/v1/variables/")

    def create_variable(
        self, name: str, value: str, type_: str, default_fields: list[str]
    ) -> dict:
        return self._request(
            "POST",
            "/api/v1/variables/",
            json={
                "name": name,
                "value": value,
                "type": type_,
                "default_fields": default_fields,
            },
        )

    def update_variable(
        self,
        variable_id: str,
        name: str,
        value: str,
        type_: str,
        default_fields: list[str],
    ) -> dict:
        return self._request(
            "PATCH",
            f"/api/v1/variables/{variable_id}",
            json={
                "id": variable_id,
                "name": name,
                "value": value,
                "type": type_,
                "default_fields": default_fields,
            },
        )


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return detail if isinstance(detail, str) else response.text[:200]


def _upsert(
    client: LangflowClient,
    existing: dict[str, dict],
    name: str,
    value: str,
    type_: str,
    default_fields: list[str],
) -> None:
    row = existing.get(name)
    if row is None:
        client.create_variable(name, value, type_, default_fields)
    else:
        client.update_variable(row["id"], name, value, type_, default_fields)


def provision_openai_compatible(
    db,
    user,
    bearer: str,
    models: list[dict],
    *,
    core_v1=None,
    transport=None,
) -> LangflowProvisionSchema:
    """Write the caller's Langflow provider variables for their active
    organization and report what Langflow now lists. Idempotent.
    ``models`` is what LiteLLM lists for the organization's key, as
    ``{"name", "label"}`` rows (api.chat.list_targets without a probe)."""
    settings = langflow_settings()
    if settings is None:
        raise LangflowError("LANGFLOW_API_URL is not set")
    if not settings.litellm_cluster_url:
        raise LangflowError("LITELLM_URL is not set")
    org = db.get(Organization, user.org_id)
    # The caller's own key, not the organization's: a flow calls LiteLLM
    # directly and sends no `user`, so the key is what attributes its
    # spend, and it can be revoked alone when the member leaves.
    key = ensure_user_key(db, org, user, core_v1)
    with LangflowClient(
        settings.api_url, bearer, transport=transport
    ) as client:
        username = client.whoami().get("username")
        if not username:
            raise LangflowError("Langflow's whoami has no username")
        existing = {
            v.get("name"): v for v in client.list_variables() if "id" in v
        }
        base_url = f"{settings.litellm_cluster_url}/v1"
        _upsert(
            client,
            existing,
            BASE_URL_VAR,
            base_url,
            "Generic",
            BASE_URL_FIELDS,
        )
        _upsert(
            client, existing, API_KEY_VAR, key, "Credential", API_KEY_FIELDS
        )
    return LangflowProvisionSchema(
        langflow_user=username,
        organization=org.name,
        models=[
            LangflowModelSchema(name=m["name"], label=m["label"])
            for m in models
        ],
    )
