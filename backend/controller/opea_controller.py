import os

from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class OPEAController(Controller):

    def _get_engine_specific_context(self, instance: InferenceInstanceSchema,
                                     engineChart: EngineChartsSchema):
        context = {
            "safety_guard_model_id": instance.model.modelId,
            "tgi": {
                "llm_model_id": instance.model.modelId
            },
            "global": {
                "huggingfacehub_api_token": os.getenv("HF_API_TOKEN"),
                "model_use_pvc": "hf-cache"
            }
        }

        return context
