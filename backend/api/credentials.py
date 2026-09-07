"""Read a workload's API key.

The value is returned once to the owner (or an org admin), after which
``shown_at`` is set and the response carries ``value: null``; an admin
can ask for it again with ``?reveal=true``. The key never enters the
database: it is read from the credentials Secret on demand.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit import record
from auth.current_user import CurrentUser, get_current_user
from auth.policy import authorize_write
from auth.roles import ROLE_ADMIN
from db.database import get_db
from logger import setup_logger
from models.inference_instance import DBInferenceInstance
from models.vectordb_instance import DBVectorDBInstance
from models.workload_credential import KIND_INFERENCE, KIND_VECTORDB
from utils.credentials import (
    CREDENTIAL_KEY,
    find_credential,
    read_credential_value,
)

router = APIRouter()

logger = setup_logger(__name__)

CredentialKind = Literal["vdb", "inf"]

# Per kind: the resource table and the label used in the 403 and 404
# details, the same words the instance routers use.
RESOURCES = {
    KIND_VECTORDB: (DBVectorDBInstance, "vector database instance"),
    KIND_INFERENCE: (DBInferenceInstance, "inference instance"),
}


class CredentialSchema(BaseModel):
    key: str
    # None once the value has been shown, unless an admin reveals it.
    value: str | None
    shown_at: datetime | None


@router.get(
    "/v1alpha1/credentials/{kind}/{resource_id}",
    response_model=CredentialSchema,
)
def get_credential(
    request: Request,
    kind: CredentialKind = Path(description="vdb or inf"),
    resource_id: UUID = Path(description="The id of the instance"),
    reveal: bool = Query(
        default=False,
        description="Return a value that was already shown; admins only",
    ),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    model, label = RESOURCES[kind]
    resource = db.query(model).filter(model.id == resource_id).first()
    if resource is None:
        raise HTTPException(
            status_code=404, detail=f"{label.capitalize()} not found"
        )
    authorize_write(user, resource, label)

    credential = find_credential(db, kind, resource_id)
    if credential is None:
        raise HTTPException(
            status_code=404, detail=f"This {label} has no credential"
        )

    first_time = credential.shown_at is None
    if not first_time and not (reveal and user.role == ROLE_ADMIN):
        return CredentialSchema(
            key=CREDENTIAL_KEY, value=None, shown_at=credential.shown_at
        )

    # Read before stamping, so a failed cluster call does not use up
    # the one-time reveal.
    try:
        value = read_credential_value(credential)
    except ApiException as e:
        logger.exception("Cannot read Secret %s", credential.secret_name)
        raise HTTPException(
            status_code=503,
            detail=f"Kubernetes is not reachable; try again later ({e.reason})",
        )
    if value is None:
        raise HTTPException(
            status_code=404,
            detail=f"The credential Secret {credential.secret_name} is missing",
        )
    if first_time:
        credential.shown_at = datetime.now()
    record(
        db,
        user=user,
        action="reveal",
        resource_kind="credentials",
        resource_id=str(resource_id),
        outcome=200,
        request_id=request.state.request_id,
        detail={"kind": kind},
    )
    db.commit()
    db.refresh(credential)
    return CredentialSchema(
        key=CREDENTIAL_KEY, value=value, shown_at=credential.shown_at
    )
