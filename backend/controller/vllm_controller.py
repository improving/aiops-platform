from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class VLLMController(Controller):

    def _get_engine_specific_context(self, instance: InferenceInstanceSchema,
                                     engineChart: EngineChartsSchema):
        context = {
            "model": instance.model.modelId,
            "args": {},
            "volumeMounts": {
                "hf_cache": {
                    "mountPath": "/model"
                }
            }
        }

        if instance.config and instance.config.quantization:
            context["quantization"] = str(instance.config.quantization.lower())
            context["dtype"] = "auto"

        # populate the argument `lora-modules` with a space separated list of adapter ids/paths
        if instance.config and instance.config.lora_adapters:
            lora_adapters = []
            for i, adapter_to_use in enumerate(instance.config.lora_adapters,
                                               start=1):
                key = f"adapter{i}"
                if adapter_to_use.path:
                    value = f"/model/{adapter_to_use.path}".replace("//", "/")
                elif adapter_to_use.hf_id:
                    value = adapter_to_use.hf_id
                else:
                    raise ValueError(
                        f"Invalid adapter config: {adapter_to_use}")
                lora_adapters.append(f"{key}={value}")

            if len(lora_adapters) > 0:
                context["args"]["lora_adapters"] = lora_adapters

        return context

    def get_service_name(self, instance: InferenceInstanceSchema,
                         engineChart: EngineChartsSchema):
        return f"{self._get_release_name(instance)}"
