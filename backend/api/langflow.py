"""Provision the caller's Langflow account for their organization.

``POST /v1alpha1/langflow/provision`` writes Langflow's "OpenAI
Compatible" provider variables (utils/langflow.py) as the caller, using
the caller's own bearer, so it needs a browser session: a personal
token or a service account has no Keycloak token Langflow would accept.
The Develop page calls it on load; it is idempotent (two variable
writes, no cluster probe).
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from api.chat import MOCK_TARGET, chat_mock_enabled, list_targets
from auth.current_user import CurrentUser, bearer, get_current_user
from db.database import get_db
from models.organization import Organization
from schemas.langflow import LangflowModelSchema, LangflowProvisionSchema
from utils.langflow import (
    LangflowError,
    langflow_settings,
    provision_openai_compatible,
)
from utils.litellm import LiteLLMError, get_client

router = APIRouter()

NEEDS_SESSION = (
    "Langflow is provisioned with your own sign-in: open the Develop "
    "page in the browser (a personal token or service account cannot "
    "be forwarded to Langflow)"
)


@router.post(
    "/v1alpha1/langflow/provision", response_model=LangflowProvisionSchema
)
def provision(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> LangflowProvisionSchema:
    if chat_mock_enabled():
        org = db.get(Organization, user.org_id)
        return LangflowProvisionSchema(
            langflow_user=user.name or user.sub,
            organization=org.name,
            models=[
                LangflowModelSchema(
                    name=MOCK_TARGET, label="Mock model · Mock"
                )
            ],
        )
    if langflow_settings() is None:
        raise HTTPException(
            status_code=503,
            detail="Langflow is not configured (LANGFLOW_API_URL)",
        )
    if not user.is_browser_session or credentials is None:
        raise HTTPException(status_code=409, detail=NEEDS_SESSION)
    if get_client() is None:
        raise HTTPException(
            status_code=503, detail="LiteLLM is not configured"
        )
    models = [
        {"name": t["name"], "label": t["label"]}
        for t in list_targets(db, user, probe=False)
    ]
    try:
        return provision_openai_compatible(
            db, user, credentials.credentials, models
        )
    except LangflowError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except LiteLLMError as exc:
        # ensure_user_key: the member's key could not be made or read.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
