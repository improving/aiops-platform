import base64
import os
from .base_controller import Controller
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from schemas.inference_instance import InferenceInstanceSchema

class HuggingFaceController(Controller):
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
        secret_name = "hf-api-token"
        hf_api_token = os.environ.get("HF_API_TOKEN")
        if not hf_api_token:
            raise ValueError("HF_API_TOKEN environment variable is not set")

        secret_data = {
            "HF_API_TOKEN": base64.b64encode(hf_api_token.encode()).decode()
        }

        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=secret_name),
            type="Opaque",
            data=secret_data
        )

        try:
            self.core_v1_api.create_namespaced_secret(self.namespace, secret)
            self.logger.info(f"Secret '{secret_name}' created successfully")
        except ApiException as e:
            if e.status == 409:
                self.logger.info(f"Secret '{secret_name}' already exists")
            else:
                self.logger.exception(f"Failed to create secret '{secret_name}': {str(e)}")
                raise