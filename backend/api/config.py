"""Runtime configuration for the UI (packaging plan, Task 1).

``GET /v1alpha1/config/ui`` needs no token, like ``/health``: the UI
fetches it once at load (``frontend/src/lib/runtimeConfig.ts``) so a
container can point the Grafana, Langflow and Jaeger embeds at the
right hosts without rebuilding the image, where ``NEXT_PUBLIC_*`` is
inlined. The values are read at call time from ``GRAFANA_URL``,
``LANGFLOW_URL`` and ``JAEGER_URL`` (the names ``make frontend`` and
``make monitoring-up`` already use), empty when unset.
"""

import os

from fastapi import APIRouter
from pydantic import BaseModel

from auth.settings import auth_settings

router = APIRouter()

GRAFANA_URL_ENV = "GRAFANA_URL"
LANGFLOW_URL_ENV = "LANGFLOW_URL"
JAEGER_URL_ENV = "JAEGER_URL"


class UIConfigSchema(BaseModel):
    grafanaUrl: str
    langflowUrl: str
    jaegerUrl: str
    authMode: str


def _url(name: str) -> str:
    return os.environ.get(name, "").strip().rstrip("/")


@router.get("/v1alpha1/config/ui", response_model=UIConfigSchema)
async def ui_config() -> UIConfigSchema:
    return UIConfigSchema(
        grafanaUrl=_url(GRAFANA_URL_ENV),
        langflowUrl=_url(LANGFLOW_URL_ENV),
        jaegerUrl=_url(JAEGER_URL_ENV),
        authMode=auth_settings().mode,
    )
