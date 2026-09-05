import os

from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class OPEAController(Controller):
    def _get_engine_specific_context(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        model_id = instance.reference or instance.model.modelId
        context = {
            "safety_guard_model_id": model_id,
            "tgi": {"llm_model_id": model_id},
            "global": {
                "huggingfacehub_api_token": os.getenv("HF_API_TOKEN"),
                "model_use_pvc": "hf-cache",
            },
        }

        return context
