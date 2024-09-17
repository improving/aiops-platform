import os

from controller.base_controller import Controller
from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema


class OPEAController(Controller):

    def _get_engine_specific_context(self, instance: InferenceInstanceSchema,
                                     engineChart: EngineChartsSchema):
        print(f"HF_API_TOKEN: {os.getenv('HF_API_TOKEN')}")
        return {
            "safety_guard_model_id": instance.model.modelId,
            "tgi": {
                "llm_model_id": instance.model.modelId
            },
            "node_selector": instance.host,
            "global": {
                "huggingfacehub_api_token": os.getenv("HF_API_TOKEN"),
                "model_use_pvc": "hf-cache"
            }
        }
