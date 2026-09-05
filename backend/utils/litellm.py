"""LiteLLM proxy client and the naming rules the platform uses in it.

Every deployed inference instance becomes one LiteLLM model named
``inst-<id8>``; each organization gets a team and one virtual key. All
calls are optional: without ``LITELLM_URL`` and ``LITELLM_MASTER_KEY``
``get_client()`` is None and callers skip the proxy.
"""

import base64
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx
from kubernetes.client.exceptions import ApiException

from logger import setup_logger
from utils.credentials import _apply_secret, _secret_body
from utils.gateway import id8
from utils.kubernetes_utils import get_core_v1_client, get_default_namespace

logger = setup_logger(__name__)

URL_ENV = "LITELLM_URL"
MASTER_KEY_ENV = "LITELLM_MASTER_KEY"
TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

ORG_KEY_SECRET_KEY = "key"
ORG_KEY_CACHE_SECONDS = 300
_org_key_cache: dict[uuid.UUID, tuple[float, str]] = {}

SPEND_LOGS_PAGE_SIZE = 500
SPEND_LOGS_MAX_PAGES = 20
SPEND_LOGS_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# (engine, category) -> (provider prefix, path suffix, LiteLLM mode). The
# OpenAI-compatible servers need their /v1 base; TEI uses the huggingface
# provider on its bare URL for both embeddings and rerank. NIM's reranker
# is not Cohere-style and OPEA is not a model: no route.
_ROUTES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("ollama", "llm"): ("openai", "/v1", "chat"),
    ("vllm", "llm"): ("openai", "/v1", "chat"),
    ("huggingface", "llm"): ("openai", "/v1", "chat"),
    ("nim", "llm"): ("openai", "/v1", "chat"),
    ("ollama", "embedding"): ("openai", "/v1", "embedding"),
    ("huggingface", "embedding"): ("huggingface", "", "embedding"),
    ("nim", "embedding"): ("openai", "/v1", "embedding"),
    ("huggingface", "reranker"): ("huggingface", "", "rerank"),
}


class LiteLLMError(Exception):
    """The proxy answered with an error or was unreachable."""


@dataclass(frozen=True)
class LiteLLMSettings:
    url: str
    master_key: str


def litellm_settings() -> LiteLLMSettings | None:
    url = os.environ.get(URL_ENV, "").strip().rstrip("/")
    key = os.environ.get(MASTER_KEY_ENV, "").strip()
    if not url or not key:
        return None
    return LiteLLMSettings(url=url, master_key=key)


def instance_model_name(instance_id: uuid.UUID) -> str:
    return f"inst-{id8(instance_id)}"


def hosted_model_name(provider_id: uuid.UUID, model: str) -> str:
    """``prov-<id8>/<model>``; ``model`` may itself contain a ``/``
    (OpenRouter ids do, for example ``openai/gpt-4o-mini``), so a
    hosted target name is split on the *first* ``/`` after the id8,
    never on every ``/``."""
    return f"prov-{id8(provider_id)}/{model}"


def hosted_litellm_params(
    provider_id: uuid.UUID,
    kind: str,
    model: str,
    capability: str,
    api_key: str | None,
    base_url: str | None,
) -> tuple[dict, dict]:
    """The ``/model/new`` params for one hosted provider model: ``kind``
    is both the platform's provider tag and the LiteLLM provider prefix
    (``openai``, ``anthropic``, ``gemini``, ``groq``, ``openrouter``)."""
    params = {"model": f"{kind}/{model}"}
    if api_key:
        params["api_key"] = api_key
    if base_url:
        params["api_base"] = base_url
    info = {
        "mode": capability,
        "aiops_provider_id": str(provider_id),
    }
    return params, info


def org_key_secret_name(org_id: uuid.UUID) -> str:
    return f"org-{id8(org_id)}-litellm-key"


def instance_litellm_params(
    engine_name: str,
    category: str,
    model_id: str,
    service_url: str,
    api_key: str | None,
) -> tuple[dict, dict] | None:
    route = _ROUTES.get((engine_name.lower(), category))
    if route is None:
        return None
    provider, suffix, mode = route
    params = {
        "model": f"{provider}/{model_id}",
        "api_base": f"{service_url.rstrip('/')}{suffix}",
    }
    if api_key:
        params["api_key"] = api_key
    return params, {"mode": mode}


class LiteLLMClient:
    def __init__(
        self,
        settings: LiteLLMSettings,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self._transport = transport

    def _client(self, stream: bool = False) -> httpx.Client:
        return httpx.Client(
            base_url=self.settings.url,
            timeout=STREAM_TIMEOUT if stream else TIMEOUT,
            transport=self._transport,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        stream: bool = False,
        api_key: str | None = None,
    ) -> httpx.Response:
        """One call with the master key (or ``api_key``); the caller closes
        a streamed response and its client (``response.close()``,
        ``response.extensions["aiops_client"].close()``)."""
        headers = {
            "authorization": f"Bearer {api_key or self.settings.master_key}"
        }
        client = self._client(stream)
        try:
            if stream:
                request = client.build_request(
                    method, path, json=json, params=params, headers=headers
                )
                response = client.send(request, stream=True)
                response.extensions["aiops_client"] = client
                return response
            response = client.request(
                method, path, json=json, params=params, headers=headers
            )
        except httpx.HTTPError as e:
            client.close()
            raise LiteLLMError(f"LiteLLM unreachable: {e}") from e
        client.close()
        if response.status_code >= 400:
            raise LiteLLMError(
                f"LiteLLM {method} {path} answered "
                f"{response.status_code}: {response.text[:300]}"
            )
        return response

    def register_model(
        self, model_name: str, litellm_params: dict, model_info: dict
    ) -> str:
        body = {
            "model_name": model_name,
            "litellm_params": litellm_params,
            "model_info": model_info,
        }
        return self.request("POST", "/model/new", json=body).json()["model_id"]

    def delete_model(self, model_id: str) -> None:
        self.request("POST", "/model/delete", json={"id": model_id})

    def create_team(
        self, alias: str, metadata: dict, max_budget: float | None = None
    ) -> str:
        body: dict = {"team_alias": alias, "metadata": metadata}
        if max_budget is not None:
            body["max_budget"] = max_budget
            body["budget_duration"] = "30d"
        return self.request("POST", "/team/new", json=body).json()["team_id"]

    def delete_team(self, team_id: str) -> None:
        self.request("POST", "/team/delete", json={"team_ids": [team_id]})

    def generate_key(self, team_id: str, alias: str, metadata: dict) -> str:
        body = {
            "team_id": team_id,
            "key_alias": alias,
            "models": [],
            "metadata": metadata,
        }
        return self.request("POST", "/key/generate", json=body).json()["key"]

    def delete_key(self, key: str) -> None:
        self.request("POST", "/key/delete", json={"keys": [key]})

    def team_info(self, team_id: str) -> dict:
        data = self.request(
            "GET", "/team/info", params={"team_id": team_id}
        ).json()
        return data.get("team_info", data)

    def update_team_budget(
        self, team_id: str, max_budget: float | None
    ) -> None:
        """``max_budget=None`` means no cap."""
        self.request(
            "POST",
            "/team/update",
            json={
                "team_id": team_id,
                "max_budget": max_budget,
                "budget_duration": "30d",
            },
        )

    def spend_logs(
        self, team_id: str, start: datetime, end: datetime
    ) -> tuple[list[dict], bool]:
        """Every spend-log row for the team between ``start`` and
        ``end`` (UTC), paging ``GET /spend/logs/ui`` at
        SPEND_LOGS_PAGE_SIZE rows per page, up to SPEND_LOGS_MAX_PAGES
        pages. Returns ``(rows, capped)``; ``capped`` is true when the
        proxy reports more rows than fit in that many pages."""
        rows: list[dict] = []
        capped = False
        for page in range(1, SPEND_LOGS_MAX_PAGES + 1):
            payload = self.request(
                "GET",
                "/spend/logs/ui",
                params={
                    "team_id": team_id,
                    "start_date": start.strftime(SPEND_LOGS_DATE_FORMAT),
                    "end_date": end.strftime(SPEND_LOGS_DATE_FORMAT),
                    "page": page,
                    "page_size": SPEND_LOGS_PAGE_SIZE,
                },
            ).json()
            data = payload.get("data") or []
            rows.extend(data)
            if payload.get("total_is_capped"):
                capped = True
            total_pages = payload.get("total_pages") or page
            if not data or page >= total_pages:
                break
        else:
            # Fell through SPEND_LOGS_MAX_PAGES pages without reaching
            # the reported last page.
            capped = True
        return rows, capped


def get_client() -> LiteLLMClient | None:
    """The proxy client, or None when LiteLLM is not configured. Tests
    patch this function."""
    settings = litellm_settings()
    if settings is None:
        return None
    return LiteLLMClient(settings)


def _read_secret_value(core_v1, name: str, namespace: str) -> str | None:
    try:
        secret = core_v1.read_namespaced_secret(name=name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            return None
        raise
    encoded = (secret.data or {}).get(ORG_KEY_SECRET_KEY)
    return base64.b64decode(encoded).decode() if encoded else None


def ensure_org_key(db, org, core_v1=None) -> str:
    """The organization's LiteLLM virtual key: created with its team on
    first use and kept in a Secret; cached for ORG_KEY_CACHE_SECONDS."""
    cached = _org_key_cache.get(org.id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    litellm = get_client()
    if litellm is None:
        raise LiteLLMError("LiteLLM is not configured")
    core_v1 = core_v1 or get_core_v1_client()
    namespace = get_default_namespace()
    secret_name = org_key_secret_name(org.id)
    key = _read_secret_value(core_v1, secret_name, namespace)
    if key is None:
        if not org.litellm_team_id:
            org.litellm_team_id = litellm.create_team(
                f"org-{org.slug}",
                {"aiops_org_id": str(org.id)},
                max_budget=float(org.budget_usd)
                if org.budget_usd is not None
                else None,
            )
        key = litellm.generate_key(
            org.litellm_team_id,
            f"org-{org.slug}-chat",
            {"aiops_org_id": str(org.id)},
        )
        _apply_secret(
            core_v1,
            namespace,
            _secret_body(secret_name, namespace, {ORG_KEY_SECRET_KEY: key}),
        )
        org.litellm_key_secret_name = secret_name
        db.commit()
    _org_key_cache[org.id] = (time.monotonic() + ORG_KEY_CACHE_SECONDS, key)
    return key
