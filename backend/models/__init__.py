"""Import every model so ``Base.metadata`` is complete.

Alembic (``alembic/env.py``) and ``db/db.py`` rely on this.
"""

from models import (
    engine_chart_dashboards,
    engine_charts,
    engines,
    finetune,
    inference_instance,
    inference_instance_dashboards,
    membership,
    model_adapters,
    models,
    notebook,
    organization,
    user,
    vectordb,
    vectordb_instance,
    workload_credential,
)
