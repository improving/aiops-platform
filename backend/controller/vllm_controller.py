from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class VLLMController(Controller):

    def _get_engine_specific_context(self, instance: InferenceInstanceSchema,
                                     engineChart: EngineChartsSchema):
        context = {
            "model": instance.model.modelId,
            "image": {},
            "env": {},
            "readManyPVC": {
                "accessModes": [],
            },
            "volumeMounts": {
                "hf_cache": {
                    "mountPath": "/model"
                }
            }
        }

        if instance.config and instance.config.quantization:
            context["quantization"] = str(instance.config.quantization.lower())
            context["dtype"] = "auto"

        return context

    def get_service_name(self, instance: InferenceInstanceSchema,
                         engineChart: EngineChartsSchema):
        return f"{self._get_release_name(instance)}"
