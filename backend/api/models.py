import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from auth.current_user import (
    ROLE_ADMIN,
    CurrentUser,
    get_current_user,
    require_admin,
)
from db.database import get_db
from models.engines import DBEngine
from models.inference_instance import DBInferenceInstance
from models.models import STATUS_PUBLISHED, DBModel
from models.serving_option import ServingOption
from registry.manual import create_manual_model
from schemas.model import ModelSchema
from schemas.serving_option import ServingOptionSchema

router = APIRouter()


def catalog_scope(user: CurrentUser):
    """Published rows only, global (``org_id`` NULL) or the caller's
    organization's own. Not ``auth.policy.org_scope``, which maps NULL
    to the *default* organization only and would hide the global
    catalog from every other organization's members."""
    return and_(
        DBModel.status == STATUS_PUBLISHED,
        or_(DBModel.org_id.is_(None), DBModel.org_id == user.org_id),
    )


def _visible_or_404(model: DBModel | None, user: CurrentUser) -> DBModel:
    """A published row is visible to anyone; a draft or deprecated one
    is admin-only, and looks the same as "not found" to everyone else."""
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.status != STATUS_PUBLISHED and user.role != ROLE_ADMIN:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


# API to get model information
@router.get("/v1alpha1/models", response_model=list[ModelSchema])
def get_models(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Retrieve the published catalog: every admin's edits become visible
    to members here only once published (drafts are managed on the
    registry, Phase 3 Task 4).

    Returns:
        List[ModelSchema]: The published models, including the count of
        adapters for each.
    """
    models = db.query(DBModel).filter(catalog_scope(user)).all()
    for model in models:
        model.countAdapters = len(model.model_adapters)
    return models


@router.get("/v1alpha1/models/{id}", response_model=ModelSchema)
def get_model(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Retrieve a specific model by its ID: any status for an admin,
    published only for a member (404 otherwise, the same as unknown).

    Args:
        id (uuid.UUID): The unique identifier of the model to retrieve.

    Returns:
        ModelSchema: The requested model, including the count of its adapters.

    Raises:
        HTTPException: If the model with the given ID is not found in the database.
    """
    model = _visible_or_404(
        db.query(DBModel).filter(DBModel.id == id).first(), user
    )
    model.countAdapters = len(model.model_adapters)
    return model


@router.get(
    "/v1alpha1/models/{id}/serving-options",
    response_model=list[ServingOptionSchema],
)
def get_model_serving_options(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    The model's serving options, left-joined with the engine rows: an
    option whose engine has no ``engines`` row (a hosted option such as
    "openrouter") comes back with ``engine_id: null`` and ``cpu: null``;
    the launch wizard renders only options with an ``engine_id``.
    """
    _visible_or_404(db.query(DBModel).filter(DBModel.id == id).first(), user)
    rows = (
        db.query(ServingOption, DBEngine)
        .outerjoin(DBEngine, DBEngine.name == ServingOption.engine)
        .filter(ServingOption.model_id == id)
        .all()
    )
    return [
        ServingOptionSchema(
            id=option.id,
            engine=option.engine,
            reference=option.reference,
            default_args=option.default_args,
            engine_id=engine.id if engine else None,
            cpu=bool(engine.cpu) if engine else None,
        )
        for option, engine in rows
    ]


@router.post("/v1alpha1/models", response_model=ModelSchema)
def create_model(
    model: ModelSchema,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """
    Create a new model in the database: an alias for the registry's
    manual create (``POST /v1alpha1/registry/manual``,
    ``registry/manual.py``), always published. Remember to checkin the
    model to the code repository.

    Args:
        model (ModelSchema): The model data to create.

    Returns:
        ModelSchema: The created model.
    """
    db_model = create_manual_model(
        db,
        name=model.name,
        model_id=model.modelId,
        category=model.category,
        subcategory=model.subcategory,
        description=model.description,
        size=model.size,
        license=model.license,
    )
    db_model.countAdapters = 0
    return db_model


@router.put("/v1alpha1/models/{id}", response_model=ModelSchema)
def update_model(
    id: uuid.UUID,
    model: ModelSchema,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """
    Update an existing model in the database.

    Args:
        model (ModelSchema): The updated model data.

    Returns:
        ModelSchema: The updated model.
    """
    db_model = db.query(DBModel).filter(DBModel.id == id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    db_model.name = model.name
    db_model.modelId = model.modelId
    db_model.description = model.description
    db_model.category = model.category
    db_model.subcategory = model.subcategory
    db_model.size = model.size
    db.commit()
    db.refresh(db_model)
    db_model.countAdapters = len(db_model.model_adapters)
    return db_model


@router.delete("/v1alpha1/models/{id}")
def delete_model(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    """
    Delete a model from the database.

    Returns:
        dict: A message confirming the deletion.

    Raises:
        HTTPException: If the model is not found or is still in use by instances.
    """
    db_model = db.query(DBModel).filter(DBModel.id == id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    ## Check if any instances are using this model
    instances = (
        db.query(DBInferenceInstance)
        .filter(DBInferenceInstance.model_id == id)
        .count()
    )
    if instances > 0:
        raise HTTPException(
            status_code=400, detail="Model is still in use by instances"
        )
    db.delete(db_model)
    db.commit()
    return {"message": "Model deleted successfully"}
