"""Import every model so ``Base.metadata`` is complete.

Alembic (``alembic/env.py``) and ``db/db.py`` rely on this.
"""

from models import (
    api_token,
    audit_event,
    engine_chart_dashboards,
    engine_charts,
    engines,
    finetune,
    inference_instance,
    inference_instance_dashboards,
    invitation,
    mcp_catalog,
    mcp_instance,
    mcp_server,
    membership,
    model_adapters,
    models,
    notebook,
    organization,
    provider,
    serving_option,
    user,
    vectordb,
    vectordb_instance,
    workload_credential,
)
