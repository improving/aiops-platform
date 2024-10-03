from fastapi import FastAPI

from api import finetune
from api.engines import router as engines_router
from api.hosts import router as hosts_router
from api.inference_instance import router as inference_instance_router
from api.model_adapters import router as model_adapters_router
from api.models import router as models_router
from api.notebooks import router as notebooks_router
from api.vectordb import router as vectordb_router
from api.vectordb_instance import router as vectordb_instance_router
from db.db import init_db, refresh_db, reload_data

app = FastAPI()

# Include the API routes
app.include_router(models_router, tags=["models"])
app.include_router(engines_router, tags=["engines"])
app.include_router(inference_instance_router, tags=["inference_instance"])
app.include_router(hosts_router, tags=["hosts"])
app.include_router(vectordb_router, tags=["vectordb"])
app.include_router(vectordb_instance_router, tags=["vectordb_instance"])
app.include_router(notebooks_router, tags=["notebooks"])
app.include_router(model_adapters_router, tags=["model_adapters"])
app.include_router(finetune.router, tags=["finetune"])


@app.post("/reload-data", tags=["utility"])
async def reload_data_endpoint():
    reload_data()
    return {"message": "Data reloaded successfully"}


@app.post("/refresh-db", tags=["utility"])
async def refresh_db_endpoint():
    refresh_db()
    return {"message": "Data refreshed successfully"}


@app.get("/health", tags=["utility"])
async def health_endpoint():
    return {"message": "OK"}


init_db()
