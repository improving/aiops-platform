"""Organization-scoped LiteLLM bookkeeping: spend, the monthly budget
for hosted providers (Phase 2b) and per-user usage from the spend logs
(Task 2 of the usage-and-metrics plan).

Imports ``_current_org``/``_org_budget`` from api/organizations.py
(tenancy); nothing there imports from here. Tests patch ``get_client``
and ``ensure_org_key`` on this module.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.chat import (
    HOSTED_PREFIX,
    MOCK_TARGET,
    TARGET_PREFIX,
    chat_mock_enabled,
    target_labels,
    user_key,
)
from api.organizations import _current_org, _org_budget
from auth.current_user import CurrentUser, get_current_user, require_admin
from auth.roles import ROLE_ADMIN
from db.database import get_db
from models.organization import Organization
from models.user import User
from utils.litellm import LiteLLMError, ensure_org_key, get_client

router = APIRouter()

# The mock target and second user for AIOPS_CHAT_MOCK usage rows, so
# the fast tier can exercise the Usage page without a LiteLLM proxy.
MOCK_USAGE_TARGET = MOCK_TARGET
MOCK_USAGE_LABEL = "Mock model · Mock"
MOCK_USAGE_OTHER_USER = "someone@example.com"

# The canned spend document for AIOPS_CHAT_MOCK, so the fast tier can
# exercise the budget card without a LiteLLM proxy.
MOCK_TEAM_ID = "team-mock"
MOCK_SPEND = 0.42
MOCK_BUDGET_RESET_AT = "2026-10-01T00:00:00Z"


class BudgetUpdateRequest(BaseModel):
    budget_usd: float | None


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


def _row_user(row: dict) -> str | None:
    """A spend-log row's ``end_user``, normalized: LiteLLM leaves it
    empty for requests made before per-user attribution shipped, or
    with the master key."""
    return row.get("end_user") or None


def _row_target(row: dict) -> str:
    return row.get("model_group") or row.get("model") or ""


def _row_model(row: dict) -> str:
    """The upstream model id without LiteLLM's provider prefix
    (``openai/qwen3:0.6b`` -> ``qwen3:0.6b``)."""
    model = row.get("model") or ""
    return model.split("/", 1)[1] if "/" in model else model


def _row_day(row: dict) -> str:
    return (row.get("startTime") or "")[:10]


def _visible_to(user: CurrentUser):
    def visible(row: dict) -> bool:
        if user.role == ROLE_ADMIN:
            return True
        return _row_user(row) == user_key(user)

    return visible


def _user_names(db: Session, keys: set[str]) -> dict[str, str]:
    """Map the ``end_user`` values LiteLLM stores (platform user ids,
    see ``user_key``) to something a person recognizes: the user's
    email, else name, else token subject. Values that are not user ids
    (rows written by other clients, or by this platform while
    ``user_key`` returned the email) stay as they are;
    ``_aggregate_usage`` relies on that to merge one person's old and
    new rows."""
    ids = []
    for key in keys:
        try:
            ids.append(uuid.UUID(key))
        except ValueError:
            continue
    if not ids:
        return {}
    users = db.query(User).filter(User.id.in_(ids)).all()
    return {str(u.id): u.email or u.name or u.sub for u in users}


def _new_bucket(target: str, label: str, model: str = "", **extra) -> dict:
    return {
        "target": target,
        "label": label,
        "model": model,
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "spend": 0.0,
        **extra,
    }


def _add_row(bucket: dict, row: dict) -> None:
    bucket["requests"] += 1
    bucket["prompt_tokens"] += row.get("prompt_tokens") or 0
    bucket["completion_tokens"] += row.get("completion_tokens") or 0
    bucket["spend"] += row.get("spend") or 0.0


def _aggregate_usage(
    rows: list[dict], labels: dict[str, str], names: dict[str, str]
) -> tuple[dict, list[dict], list[dict]]:
    """Aggregate visible spend-log rows by ``(display name, model_group,
    day)`` for the per-user-and-day table, and by target for the
    by-target table; return ``(totals, by_target, rows)``. ``names``
    maps ``end_user`` values to display names (``_user_names``). This
    merge is what an admin sees: a member's rows are filtered
    server-side by user id (``current_org_usage``), so a member never
    receives their own email-keyed rows to merge in the first place."""
    totals = _new_bucket("", "")
    by_target: dict[str, dict] = {}
    by_key: dict[tuple, dict] = {}

    for row in rows:
        user = _row_user(row)
        target = _row_target(row)
        day = _row_day(row)
        model = _row_model(row)
        # A deleted instance or provider model has no label any more;
        # its model still tells what ran there.
        label = labels.get(target) or (
            f"{target} (deleted)"
            if target.startswith((TARGET_PREFIX, HOSTED_PREFIX))
            else target
        )

        _add_row(totals, row)
        _add_row(
            by_target.setdefault(target, _new_bucket(target, label, model)),
            row,
        )
        # Key by the display name, not the raw ``end_user``: rows written
        # while ``user_key`` returned the email (before 4f7a7f2 switched
        # it to the user id) and rows written after both belong to one
        # person. The UI keys its table rows by (user, target, day), so
        # one person must land in one row. Rows with no ``end_user`` at
        # all (before attribution shipped) stay unattributed.
        display = names.get(user, user) if user else None
        _add_row(
            by_key.setdefault(
                (display, target, day),
                _new_bucket(target, label, model, user=display, day=day),
            ),
            row,
        )

    del totals["target"]
    del totals["label"]
    del totals["model"]

    targets = sorted(
        by_target.values(), key=lambda e: (-e["spend"], -e["requests"])
    )
    # Stable sorts compose: order by (user, target) first, then bring
    # the most recent day to the front without disturbing that order
    # among rows that share a day.
    entries = sorted(
        by_key.values(), key=lambda e: (e["user"] or "", e["target"])
    )
    entries.sort(key=lambda e: e["day"], reverse=True)
    return totals, targets, entries


def _mock_usage_rows(user: CurrentUser, now: datetime) -> list[dict]:
    me = user_key(user)
    today = now.strftime("%Y-%m-%dT00:00:00Z")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    return [
        {
            "model_group": MOCK_USAGE_TARGET,
            "model": "mock/mock-model",
            "end_user": me,
            "startTime": today,
            "prompt_tokens": 12,
            "completion_tokens": 24,
            "spend": 0.01,
        },
        {
            "model_group": MOCK_USAGE_TARGET,
            "model": "mock/mock-model",
            "end_user": me,
            "startTime": yesterday,
            "prompt_tokens": 8,
            "completion_tokens": 16,
            "spend": 0.02,
        },
        {
            "model_group": MOCK_USAGE_TARGET,
            "model": "mock/mock-model",
            "end_user": MOCK_USAGE_OTHER_USER,
            "startTime": today,
            "prompt_tokens": 20,
            "completion_tokens": 40,
            "spend": 0.03,
        },
    ]


@router.get("/v1alpha1/organizations/current/usage")
async def current_org_usage(
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    org = _current_org(db, user)
    now = datetime.now(UTC)
    since = (now - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    scope = "organization" if user.role == ROLE_ADMIN else "user"

    if chat_mock_enabled():
        rows, capped = _mock_usage_rows(user, now), False
    else:
        litellm = get_client()
        if litellm is None:
            raise HTTPException(
                status_code=503, detail="LiteLLM is not configured"
            )
        # Members only ever need their own rows: ask LiteLLM for just
        # those, so the page cap applies to them alone.
        end_user = None if user.role == ROLE_ADMIN else user_key(user)
        try:
            await asyncio.to_thread(ensure_org_key, db, org)
            if not org.litellm_team_id:
                raise HTTPException(
                    status_code=503,
                    detail="The organization has no LiteLLM team yet",
                )
            rows, capped = await asyncio.to_thread(
                litellm.spend_logs, org.litellm_team_id, since, now, end_user
            )
        except LiteLLMError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except ApiException as e:
            raise HTTPException(
                status_code=503,
                detail=f"Cannot read the organization key: {e.reason}",
            )

    # Backstop for the server-side ``end_user`` filter above.
    visible = list(filter(_visible_to(user), rows))
    labels = await asyncio.to_thread(target_labels, db, user)
    if chat_mock_enabled():
        labels[MOCK_USAGE_TARGET] = MOCK_USAGE_LABEL
    names = await asyncio.to_thread(
        _user_names, db, {u for u in map(_row_user, visible) if u}
    )
    totals, by_target, entries = _aggregate_usage(visible, labels, names)
    return {
        "days": days,
        "since": since.isoformat(),
        "until": now.isoformat(),
        "scope": scope,
        "capped": capped,
        "totals": totals,
        "by_target": by_target,
        "rows": entries,
    }
