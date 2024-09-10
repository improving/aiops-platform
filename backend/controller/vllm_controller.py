from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema

class VLLMController(Controller):
    def _get_engine_specific_context(self, instance: InferenceInstanceSchema):
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