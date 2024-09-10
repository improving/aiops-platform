from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema

class TGIController(Controller):
    def _get_engine_specific_context(self, instance: InferenceInstanceSchema):
        context = {
            "config": {
                "modelID": instance.model.modelId
            },
            "env": {
                "HF_HUB_OFFLINE": "1"
            },
            "volumes": {
                "shm": {"sizeLimit": "1Gi"}
            },
            "strategy": {},
            "serviceMonitor": {
                "additionalLabels": {}
            },
            "livenessProbe": {
                "httpGet": {},
            },
            "readinessProbe": {
                "httpGet": {},
            }
        }
        
        if instance.config and instance.config.maxInputLength:
            context["env"]["MAX_INPUT_TOKENS"] = str(instance.config.maxInputLength)
        
        if instance.config and instance.config.maxTokens:
            context["env"]["MAX_TOTAL_TOKENS"] = str(instance.config.maxTokens)
        
        return context

    async def install(self, instance: InferenceInstanceSchema):
        await self._create_hf_api_token_secret()
        await super().install(instance)

    async def _create_hf_api_token_secret(self):
        # Implementation remains the same as in the original TGIController
        pass