import base64
import os

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class HuggingFaceController(Controller):
    def _get_engine_specific_context(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        context = {
            "config": {"modelID": instance.model.modelId},
            "env": [],
            "volumes": {
                "hf_cache": {
                    "claimName": "hf-cache",
                },
                "shm": {"sizeLimit": "1Gi"},
            },
            "strategy": {},
            "serviceMonitor": {"additionalLabels": {}},
            "livenessProbe": {
                "httpGet": {},
            },
            "readinessProbe": {
                "httpGet": {},
            },
            "volumeMounts": {"hf_cache": {}},
        }

        if instance.config.enable_tracing:
            if instance.config.env_vars is None:
                instance.config.env_vars = {}
            instance.config.env_vars["OTLP_ENDPOINT"] = os.environ.get(
                "TRACING_URL",
                "grpc://infra-jaeger-collector.observability.svc:4317",
            )
            instance.config.env_vars["OTLP_SERVICE_NAME"] = (
                self.get_service_name(instance, engineChart)
            )

        if instance.config and instance.config.maxInputLength:
            context["env"].append(
                {
                    "name": "MAX_INPUT_TOKENS",
                    "value": str(instance.config.maxInputLength),
                }
            )

        if instance.config and instance.config.maxTokens:
            context["env"].append(
                {
                    "name": "MAX_TOTAL_TOKENS",
                    "value": str(instance.config.maxTokens),
                }
            )

        self.get_env_vars(instance, context)

        if instance.config and instance.config.lora_adapters:
            lora_adapters_paths = []
            for adapter_to_use in instance.config.lora_adapters:
                if adapter_to_use.hf_id:
                    lora_adapters_paths.append(adapter_to_use.hf_id)
                elif adapter_to_use.path:
                    lora_adapters_paths.append(
                        f"/root/.cache/huggingface/hub/{adapter_to_use.path}".replace(
                            "//", "/"
                        )
                    )

            if lora_adapters_paths:
                context["env"].append(
                    {
                        "name": "lora_adapters",
                        "value": ",".join(lora_adapters_paths),
                    }
                )

        return context

    def get_env_vars(self, instance: InferenceInstanceSchema, context):
        env_vars = []

        # Load the default values first
        default_env = {}
        if instance.engine.default_config:
            model_type = instance.model.category
            for default_config in instance.engine.default_config:
                if default_config.chart_type == model_type:
                    default_env[default_config.name] = (
                        default_config.defaultValue
                    )

        # Merge with instance.config.env_vars, preferring the latter
        if instance.config and instance.config.env_vars:
            for key, value in instance.config.env_vars.items():
                default_env[key] = value

        # Create the final env_vars list
        for key, value in default_env.items():
            env_vars.append(
                {
                    "name": key,
                    "value": str(value),  # Ensure the value is a string
                }
            )

        self.logger.info(f"Final env vars: {env_vars}")
        context["env"] = env_vars

    async def install(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
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
            data=secret_data,
        )

        try:
            self.core_v1_api.create_namespaced_secret(self.namespace, secret)
            self.logger.info(f"Secret '{secret_name}' created successfully")
        except ApiException as e:
            if e.status == 409:
                self.logger.info(f"Secret '{secret_name}' already exists")
            else:
                self.logger.exception(
                    f"Failed to create secret '{secret_name}': {str(e)}"
                )
                raise
