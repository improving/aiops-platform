"""Organization-scoped LiteLLM bookkeeping: spend and the monthly
budget for hosted providers (Phase 2b)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.chat import chat_mock_enabled
from auth.current_user import CurrentUser, get_current_user, require_admin
from db.database import get_db
from logger import setup_logger
from models.organization import Organization
from utils.litellm import LiteLLMError, ensure_org_key, get_client

router = APIRouter()
logger = setup_logger(__name__)

# The canned spend document for AIOPS_CHAT_MOCK, so the fast tier can
# exercise the budget card without a LiteLLM proxy.
MOCK_TEAM_ID = "team-mock"
MOCK_SPEND = 0.42
MOCK_BUDGET_RESET_AT = "2026-10-01T00:00:00Z"


class BudgetUpdateRequest(BaseModel):
    budget_usd: float | None


def _org_budget(org: Organization) -> float | None:
    return float(org.budget_usd) if org.budget_usd is not None else None


def _spend_document(
    org: Organization,
    team_id: str | None,
    spend: float,
    max_budget: float | None,
    budget_reset_at: str | None,
) -> dict:
    return {
        "team_id": team_id,
        "spend": spend,
        "max_budget": max_budget,
        "budget_reset_at": budget_reset_at,
        "budget_usd": _org_budget(org),
    }


def _current_org(db: Session, user: CurrentUser) -> Organization:
    return (
        db.query(Organization).filter(Organization.id == user.org_id).first()
    )


@router.get("/v1alpha1/organizations/current/spend")
async def current_org_spend(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    org = _current_org(db, user)
    if chat_mock_enabled():
        return _spend_document(
            org,
            MOCK_TEAM_ID,
            MOCK_SPEND,
            _org_budget(org),
            MOCK_BUDGET_RESET_AT,
        )
    litellm = get_client()
    if litellm is None:
        raise HTTPException(
            status_code=503, detail="LiteLLM is not configured"
        )
    try:
        await asyncio.to_thread(ensure_org_key, db, org)
        info = await asyncio.to_thread(litellm.team_info, org.litellm_team_id)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ApiException as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot read the organization key: {e.reason}",
        )
    return _spend_document(
        org,
        org.litellm_team_id,
        info.get("spend", 0.0),
        info.get("max_budget"),
        info.get("budget_reset_at"),
    )


@router.put("/v1alpha1/organizations/current/budget")
async def update_org_budget(
    body: BudgetUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    org = _current_org(db, user)

    if chat_mock_enabled():
        org.budget_usd = body.budget_usd
        db.commit()
        return _spend_document(
            org,
            MOCK_TEAM_ID,
            MOCK_SPEND,
            body.budget_usd,
            MOCK_BUDGET_RESET_AT,
        )
    litellm = get_client()
    if litellm is None:
        raise HTTPException(
            status_code=503, detail="LiteLLM is not configured"
        )
    try:
        await asyncio.to_thread(ensure_org_key, db, org)
        await asyncio.to_thread(
            litellm.update_team_budget, org.litellm_team_id, body.budget_usd
        )
        # The row follows the proxy: a failed update leaves both unchanged.
        org.budget_usd = body.budget_usd
        db.commit()
        info = await asyncio.to_thread(litellm.team_info, org.litellm_team_id)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ApiException as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot read the organization key: {e.reason}",
        )
    return _spend_document(
        org,
        org.litellm_team_id,
        info.get("spend", 0.0),
        info.get("max_budget"),
        info.get("budget_reset_at"),
    )
