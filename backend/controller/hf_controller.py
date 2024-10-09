import base64
import os

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class HuggingFaceController(Controller):

    def _get_engine_specific_context(self, instance: InferenceInstanceSchema,
                                     engineChart: EngineChartsSchema):
        context = {
            "config": {
                "modelID": instance.model.modelId
            },
            "env": {
                "HF_HUB_OFFLINE": "1",
                "HF_HOME": "/root/.cache/huggingface"
            },
            "volumes": {
                "hf_cache": {
                    "claimName": "hf-cache",
                },
                "shm": {
                    "sizeLimit": "1Gi"
                }
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
            },
            "volumeMounts": {
                "hf_cache": {
                    "mountPath": "/root/.cache/huggingface/hub"
                }
            },
        }

        if instance.config and instance.config.maxInputLength:
            context["env"]["MAX_INPUT_TOKENS"] = str(
                instance.config.maxInputLength)

        if instance.config and instance.config.maxTokens:
            context["env"]["MAX_TOTAL_TOKENS"] = str(instance.config.maxTokens)

        self.logger.info(f"Lora adapters: {instance.config.lora_adapters}")

        if instance.config and instance.config.lora_adapters:
            lora_adapters_paths = []
            for adapter_to_use in instance.config.lora_adapters:
                if adapter_to_use.hf_id:
                    lora_adapters_paths.append(adapter_to_use.hf_id)
                elif adapter_to_use.path:
                    lora_adapters_paths.append(
                        f"/root/.cache/huggingface/hub/{adapter_to_use.path}".
                        replace("//", "/"))

            if lora_adapters_paths:
                context["env"]["lora_adapters"] = ",".join(lora_adapters_paths)

        return context

    async def install(self, instance: InferenceInstanceSchema,
                      engineChart: EngineChartsSchema):
        self.create_ns_if_needed()
        await self._create_hf_api_token_secret()
        await super().install(instance, engineChart)

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
            data=secret_data)

        try:
            self.core_v1_api.create_namespaced_secret(self.namespace, secret)
            self.logger.info(f"Secret '{secret_name}' created successfully")
        except ApiException as e:
            if e.status == 409:
                self.logger.info(f"Secret '{secret_name}' already exists")
            else:
                self.logger.exception(
                    f"Failed to create secret '{secret_name}': {str(e)}")
                raise
