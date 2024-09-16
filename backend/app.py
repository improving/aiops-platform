from fastapi import FastAPI

from api.db import init_db, refresh_db, reload_data
from api.engines import router as engines_router
from api.hosts import router as hosts_router
from api.inference_instance import router as inference_instance_router
from api.models import router as models_router

app = FastAPI()

# Include the API routes
app.include_router(models_router)
app.include_router(engines_router)
app.include_router(inference_instance_router)
app.include_router(hosts_router)


@app.post("/reload-data")
async def reload_data_endpoint():
    reload_data()
    return {"message": "Data reloaded successfully"}


@app.post("/refresh-db")
async def refresh_db_endpoint():
    refresh_db()
    return {"message": "Data refreshed successfully"}


@app.get("/health")
async def health_endpoint():
    return {"message": "OK"}


init_db()
