import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from models.inference_instance import DBInferenceInstance
from models.models import DBModel
from schemas.model import ModelSchema

router = APIRouter()


# API to get model information
@router.get("/v1alpha1/models", response_model=list[ModelSchema])
def get_models(db: Session = Depends(get_db)):
    """
    Retrieve all models from the database.

    Returns:
        List[ModelSchema]: A list of all models, including the count of adapters for each.

    Raises:
        HTTPException: If no models are found in the database.
    """
    models = db.query(DBModel).all()
    if not models:
        raise HTTPException(status_code=404, detail="No models found")
    for model in models:
        model.countAdapters = len(model.model_adapters)
    return models


@router.get("/v1alpha1/models/{id}", response_model=ModelSchema)
def get_model(id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Retrieve a specific model by its ID.

    Args:
        id (uuid.UUID): The unique identifier of the model to retrieve.

    Returns:
        ModelSchema: The requested model, including the count of its adapters.

    Raises:
        HTTPException: If the model with the given ID is not found in the database.
    """
    model = db.query(DBModel).filter(DBModel.id == id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    model.countAdapters = len(model.model_adapters)
    return model


@router.post("/v1alpha1/models", response_model=ModelSchema)
def create_model(model: ModelSchema, db: Session = Depends(get_db)):
    """
    Create a new model in the database. Remember to checkin the model
    to the code repository.

    Args:
        model (ModelSchema): The model data to create.

    Returns:
        ModelSchema: The created model.
    """
    db_model = DBModel(**model.model_dump(exclude={"countAdapters"}))
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    return db_model


@router.put("/v1alpha1/models/{id}", response_model=ModelSchema)
def update_model(
    id: uuid.UUID, model: ModelSchema, db: Session = Depends(get_db)
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
def delete_model(id: uuid.UUID, db: Session = Depends(get_db)):
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
