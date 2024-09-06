import os
from fastapi import APIRouter, HTTPException, Depends
from typing import List
import uuid
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session, relationship
from .database import Base, get_db
from .models import DBModel
from .engines import DBEngine
from .controller_utils import get_controller
from schemas.inference_instance import InferenceInstanceSchema, InferenceInstanceConfigParamsSchema
from schemas.model import ModelSchema
from schemas.engine import EngineSchema

router = APIRouter()

# SQLAlchemy models
class DBInferenceInstanceConfigParams(Base):
    __tablename__ = "inference_instance_config_params"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maxInputLength = Column(Integer)
    maxTokens = Column(Integer)
    maxBatchPrefillTokens = Column(Integer)
    maxBatchTotalTokens = Column(Integer)
    quantization = Column(String)
    image = Column(String)

class DBInferenceInstance(Base):
    __tablename__ = "inference_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id = Column(UUID(as_uuid=True), ForeignKey('models.id'))
    engine_id = Column(UUID(as_uuid=True), ForeignKey('engines.id'))
    host = Column(String)
    endpoint = Column(String)
    healthEndpoint = Column(String)
    metricsEndpoint = Column(String)
    config_id = Column(UUID(as_uuid=True), ForeignKey('inference_instance_config_params.id'))

    model = relationship("DBModel")
    engine = relationship("DBEngine")
    config = relationship("DBInferenceInstanceConfigParams")

@router.get("/v1alpha1/inferenceInstance", response_model=List[InferenceInstanceSchema])
def list_inference_instances(db: Session = Depends(get_db)):
    instances = db.query(DBInferenceInstance).all()
    return instances

@router.get("/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstanceSchema)
def get_inference_instance(id: uuid.UUID, db: Session = Depends(get_db)):
    instance = db.query(DBInferenceInstance).filter(DBInferenceInstance.id == id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Inference instance not found")
    return instance

@router.post("/v1alpha1/inferenceInstance", response_model=InferenceInstanceSchema)
async def create_inference_instance(instance: InferenceInstanceSchema, db: Session = Depends(get_db)):
    # Fetch the full model and engine objects
    model = db.query(DBModel).filter(DBModel.id == instance.model.id).first()
    engine = db.query(DBEngine).filter(DBEngine.id == instance.engine.id).first()
    
    if not model or not engine:
        raise HTTPException(status_code=404, detail="Model or Engine not found")

    HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
    NGC_API_KEY = os.environ.get("NGC_API_KEY")

    if engine.name == 'nim' and not NGC_API_KEY:
        raise HTTPException(status_code=400, detail="NGC API key not set")
    elif not HF_API_TOKEN:
        raise HTTPException(status_code=400, detail="HuggingFace API token not set.")

    # Create config if provided, otherwise use default values
    config_data = instance.config.dict() if instance.config else {}
    db_config = DBInferenceInstanceConfigParams(**config_data)
    
    db_instance = DBInferenceInstance(
        model_id=instance.model.id,
        engine_id=instance.engine.id,
        host=instance.host,
        endpoint=instance.endpoint or "",
        healthEndpoint=instance.healthEndpoint or "",
        metricsEndpoint=instance.metricsEndpoint or "",
        config=db_config
    )
    db.add(db_config)
    db.add(db_instance)
    db.commit()
    db.refresh(db_instance)

    # Construct the full InferenceInstanceSchema for the response and controller
    full_instance = InferenceInstanceSchema(
        id=db_instance.id,
        model=ModelSchema.from_orm(model),
        engine=EngineSchema.from_orm(engine),
        host=db_instance.host,
        config=InferenceInstanceConfigParamsSchema.from_orm(db_config) if db_config else None,
        endpoint=db_instance.endpoint,
        healthEndpoint=db_instance.healthEndpoint,
        metricsEndpoint=db_instance.metricsEndpoint
    )

    # Get the appropriate controller
    controller = await get_controller(engine.name)

    # Install the Helm chart
    try:
        await controller.install(full_instance)
    except Exception as e:
        db.delete(db_instance)
        db.delete(db_config)
        db.commit()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to install Helm chart: {str(e)}")

    return full_instance

@router.patch("/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstanceSchema)
async def update_inference_instance(id: uuid.UUID, updated_instance: InferenceInstanceSchema, db: Session = Depends(get_db)):
    db_instance = db.query(DBInferenceInstance).filter(DBInferenceInstance.id == id).first()
    if not db_instance:
        raise HTTPException(status_code=404, detail="Inference instance not found")

    for key, value in updated_instance.dict(exclude_unset=True).items():
        if key == 'config':
            for config_key, config_value in value.items():
                setattr(db_instance.config, config_key, config_value)
        else:
            setattr(db_instance, key, value)

    db.commit()
    db.refresh(db_instance)

    # Get the appropriate controller
    controller = await get_controller(db_instance.engine.name)

    # Upgrade the Helm chart
    try:
        await controller.upgrade(db_instance)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upgrade Helm chart: {str(e)}")

    return db_instance

@router.delete("/v1alpha1/inferenceInstance/{id}")
async def delete_inference_instance(id: uuid.UUID, db: Session = Depends(get_db)):
    db_instance = db.query(DBInferenceInstance).filter(DBInferenceInstance.id == id).first()
    if not db_instance:
        raise HTTPException(status_code=404, detail="Inference instance not found")

    # Get the appropriate controller
    controller = await get_controller(db_instance.engine.name)

    # Remove the Helm chart
    try:
        await controller.remove(db_instance)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove Helm chart: {str(e)}")

    db.delete(db_instance.config)
    db.delete(db_instance)
    db.commit()

    return {"detail": "Inference instance deleted"}
