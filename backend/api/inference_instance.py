from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from .db import get_db_connection
from .models import Model  # Import the Model class
from .engines import Engine  # Import the Engine class
from .hosts import Host, get_host_details  # Import the Host class and a function to get host details

router = APIRouter()

class InferenceInstanceConfigParams(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    maxInputLength: int
    maxTokens: int
    maxBatchPrefillTokens: int
    maxBatchTotalTokens: int
    quantization: str
    image: str

# Pydantic model for InferenceInstance
class InferenceInstance(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    model: Model  # Full model object
    engine: Engine  # Full engine object
    host: str  # Store only the host name
    config: InferenceInstanceConfigParams
    endpoint: Optional[str] = ""
    healthEndpoint: Optional[str] = ""
    metricsEndpoint: Optional[str] = ""
    

# API to list existing inference instances
@router.get("/v1alpha1/inferenceInstance", response_model=List[InferenceInstance])
def list_inference_instances():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ii.id, ii.host, ii.endpoint, ii.healthEndpoint, ii.metricsEndpoint, ii.model_id, ii.engine_id, ii.inference_instance_config_params_id,
               m.name AS model_name, m.modelId, m.description AS model_description, m.category, m.subcategory, m.size,
               e.name AS engine_name, e.description AS engine_description, e.helm_chart_repo,
               icp.maxInputLength, icp.maxTokens, icp.maxBatchPrefillTokens, icp.maxBatchTotalTokens, icp.quantization, icp.image
        FROM inference_instances ii
        JOIN models m ON ii.model_id = m.id
        JOIN engines e ON ii.engine_id = e.id
        JOIN inference_instance_config_params icp ON ii.inference_instance_config_params_id = icp.id
    """)
    rows = cursor.fetchall()
    conn.close()
    
    instances = []
    for row in rows:
        instance = InferenceInstance(
            id=row['id'],
            model=Model(
                id=row['model_id'],
                name=row['model_name'],
                modelId=row['modelId'],
                description=row['model_description'],
                category=row['category'],
                subcategory=row['subcategory'],
                size=row['size']
            ),
            engine=Engine(
                id=row['engine_id'],
                name=row['engine_name'],
                description=row['engine_description'],
                helm_chart_repo=row['helm_chart_repo']
            ),
            host=row['host'],
            endpoint=row['endpoint'],
            healthEndpoint=row['healthEndpoint'],
            metricsEndpoint=row['metricsEndpoint'],
            config=InferenceInstanceConfigParams(
                id=row['inference_instance_config_params_id'],
                maxInputLength=row['maxInputLength'],
                maxTokens=row['maxTokens'],
                maxBatchPrefillTokens=row['maxBatchPrefillTokens'],
                maxBatchTotalTokens=row['maxBatchTotalTokens'],
                quantization=row['quantization'],
                image=row['image']
            )
        )
        instances.append(instance)
    
    return instances

@router.get("/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstance)
def get_inference_instance(id: uuid.UUID):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ii.id, ii.host, ii.endpoint, ii.healthEndpoint, ii.metricsEndpoint, ii.model_id, ii.engine_id, ii.inference_instance_config_params_id,
               m.name AS model_name, m.modelId, m.description AS model_description, m.category, m.subcategory, m.size,
               e.name AS engine_name, e.description AS engine_description, e.helm_chart_repo,
               icp.maxInputLength, icp.maxTokens, icp.maxBatchPrefillTokens, icp.maxBatchTotalTokens, icp.quantization, icp.image
        FROM inference_instances ii
        JOIN models m ON ii.model_id = m.id
        JOIN engines e ON ii.engine_id = e.id
        JOIN inference_instance_config_params icp ON ii.inference_instance_config_params_id = icp.id
        WHERE ii.id = ?
    """, (str(id),))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Inference instance not found")
    instance = InferenceInstance(
        id=row['id'],
        model=Model(
            id=row['model_id'],
            name=row['model_name'],
            modelId=row['modelId'],
            description=row['model_description'],
            category=row['category'],
            subcategory=row['subcategory'],
            size=row['size']
        ),
        engine=Engine(
            id=row['engine_id'],
            name=row['engine_name'],
            description=row['engine_description'],
            helm_chart_repo=row['helm_chart_repo']
        ),
        host=row['host'],
        endpoint=row['endpoint'],
        healthEndpoint=row['healthEndpoint'],
        metricsEndpoint=row['metricsEndpoint'],
        config=InferenceInstanceConfigParams(
            id=row['inference_instance_config_params_id'],
            maxInputLength=row['maxInputLength'],
            maxTokens=row['maxTokens'],
            maxBatchPrefillTokens=row['maxBatchPrefillTokens'],
            maxBatchTotalTokens=row['maxBatchTotalTokens'],
            quantization=row['quantization'],
            image=row['image']
        )
    )
    
    return instance

# API to create a new inference instance
@router.post("/v1alpha1/inferenceInstance", response_model=InferenceInstance)
def create_inference_instance(instance: InferenceInstance):
    conn = get_db_connection()
    cursor = conn.cursor()
    # insert inference_instance_config_params & get the id  
    cursor.execute(
        "INSERT INTO inference_instance_config_params (id, maxInputLength, maxTokens, maxBatchPrefillTokens, maxBatchTotalTokens, quantization, image) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(instance.config.id), instance.config.maxInputLength, instance.config.maxTokens, instance.config.maxBatchPrefillTokens, instance.config.maxBatchTotalTokens, instance.config.quantization, instance.config.image)
    )
    cursor.execute(
        "INSERT INTO inference_instances (id, model_id, engine_id, host, endpoint, healthEndpoint, metricsEndpoint, inference_instance_config_params_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(instance.id), str(instance.model.id), str(instance.engine.id), instance.host, instance.endpoint, instance.healthEndpoint, instance.metricsEndpoint, str(instance.config.id))
    )
    conn.commit()
    print(f"instance.id: {str(instance.id)}")
    # fetch the instance with all the details including the model and engine details from respective tables
    cursor.execute("""
        SELECT ii.id, ii.host, ii.endpoint, ii.healthEndpoint, ii.metricsEndpoint, ii.model_id, ii.engine_id, ii.inference_instance_config_params_id,
               m.name AS model_name, m.modelId, m.description AS model_description, m.category, m.subcategory, m.size,
               e.name AS engine_name, e.description AS engine_description, e.helm_chart_repo,
               icp.maxInputLength, icp.maxTokens, icp.maxBatchPrefillTokens, icp.maxBatchTotalTokens, icp.quantization, icp.image
        FROM inference_instances ii
        JOIN models m ON ii.model_id = m.id
        JOIN engines e ON ii.engine_id = e.id
        JOIN inference_instance_config_params icp ON ii.inference_instance_config_params_id = icp.id
        WHERE ii.id = ?
    """, (str(instance.id),))
    row = cursor.fetchone()
    conn.close()

    instance = InferenceInstance(
        id=row['id'],
        model=Model(
            id=row['model_id'],
            name=row['model_name'],
            modelId=row['modelId'],
            description=row['model_description'],
            category=row['category'],
            subcategory=row['subcategory'],
            size=row['size']
        ),
        engine=Engine(
            id=row['engine_id'],
            name=row['engine_name'],
            description=row['engine_description'],
            helm_chart_repo=row['helm_chart_repo']
        ),
        host=row['host'],
        endpoint=row['endpoint'],
        healthEndpoint=row['healthEndpoint'],
        metricsEndpoint=row['metricsEndpoint'],
        config=InferenceInstanceConfigParams(
            id=row['inference_instance_config_params_id'],
            maxInputLength=row['maxInputLength'],
            maxTokens=row['maxTokens'],
            maxBatchPrefillTokens=row['maxBatchPrefillTokens'],
            maxBatchTotalTokens=row['maxBatchTotalTokens'],
            quantization=row['quantization'],
            image=row['image']
        )
    )
    return instance

# API to update an existing inference instance
@router.patch("/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstance)
def update_inference_instance(id: uuid.UUID, updated_instance: InferenceInstance):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE inference_instance_config_params SET maxInputLength = ?, maxTokens = ?, maxBatchPrefillTokens = ?, maxBatchTotalTokens = ?, quantization = ?, image = ? WHERE id = ?",
        (updated_instance.config.maxInputLength, updated_instance.config.maxTokens, updated_instance.config.maxBatchPrefillTokens, updated_instance.config.maxBatchTotalTokens, updated_instance.config.quantization, updated_instance.config.image, str(updated_instance.config.id))
    )
    cursor.execute(
        "UPDATE inference_instances SET model_id = ?, engine_id = ?, host = ?, endpoint = ?, healthEndpoint = ?, metricsEndpoint = ? WHERE id = ?",
        (str(updated_instance.model.id), str(updated_instance.engine.id), updated_instance.host, updated_instance.endpoint, updated_instance.healthEndpoint, updated_instance.metricsEndpoint, str(id))
    )
    conn.commit()
    
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Inference instance not found")


    # fetch the updated instance
    cursor.execute("""
        SELECT ii.id, ii.host, ii.endpoint, ii.healthEndpoint, ii.metricsEndpoint, ii.model_id, ii.engine_id, ii.inference_instance_config_params_id,
               m.name AS model_name, m.modelId, m.description AS model_description, m.category, m.subcategory, m.size,
               e.name AS engine_name, e.description AS engine_description, e.helm_chart_repo,
               icp.maxInputLength, icp.maxTokens, icp.maxBatchPrefillTokens, icp.maxBatchTotalTokens, icp.quantization, icp.image
        FROM inference_instances ii
        JOIN models m ON ii.model_id = m.id
        JOIN engines e ON ii.engine_id = e.id
        JOIN inference_instance_config_params icp ON ii.inference_instance_config_params_id = icp.id
        WHERE ii.id = ?
    """, (str(id),))
    row = cursor.fetchone()
    conn.close()

    host_details = get_host_details(row['host'])  # Fetch host details using the host name
    instance = InferenceInstance(
        id=row['id'],
        model=Model(
            id=row['model_id'],
            name=row['model_name'],
            modelId=row['modelId'],
            description=row['model_description'],
            category=row['category'],
            subcategory=row['subcategory'],
            size=row['size']
        ),
        engine=Engine(
            id=row['engine_id'],
            name=row['engine_name'],
            description=row['engine_description'],
            helm_chart_repo=row['helm_chart_repo']
        ),
        host=row['host'],
        endpoint=row['endpoint'],
        healthEndpoint=row['healthEndpoint'],
        metricsEndpoint=row['metricsEndpoint'],
        config=InferenceInstanceConfigParams(
            id=row['inference_instance_config_params_id'],
            maxInputLength=row['maxInputLength'],
            maxTokens=row['maxTokens'],
            maxBatchPrefillTokens=row['maxBatchPrefillTokens'],
            maxBatchTotalTokens=row['maxBatchTotalTokens'],
            quantization=row['quantization'],
            image=row['image']
        )
    )
    return instance

# API to delete an inference instance
@router.delete("/v1alpha1/inferenceInstance/{id}")
def delete_inference_instance(id: uuid.UUID):
    conn = get_db_connection()
    cursor = conn.cursor()
    # get the inference_instance_config_params_id from inference_instances table
    cursor.execute("SELECT inference_instance_config_params_id FROM inference_instances WHERE id = ?", (str(id),))
    row = cursor.fetchone()
    config_id = row['inference_instance_config_params_id']
    cursor.execute("DELETE FROM inference_instances WHERE id = ?", (str(id),))
    cursor.execute("DELETE FROM inference_instance_config_params WHERE id = ?", (str(config_id),))
    conn.commit()
    conn.close()
    
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Inference instance not found")
    
    return {"detail": "Inference instance deleted"}
