import asyncio
import os

from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema
from utils.credentials import CREDENTIAL_KEY, credential_secret_names

from .base_controller import Controller

LIVENESS_INITIAL_DELAY_SECONDS = 1800
VLLM_CACHE_ROOT = "/model/.vllm-cache"


class VLLMController(Controller):
    # vllm serve rejects a request without VLLM_API_KEY, so the key is
    # needed even on the in-cluster route that skips the gateway.
    workload_checks_api_key = True

    def _get_engine_specific_context(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        # vllm serve reads VLLM_API_KEY (Task 14): the chart's plain env
        # list lets us reference the credentials Secret with a
        # secretKeyRef instead of rendering the value into the template.
        credential_secret_name, _ = credential_secret_names("inf", instance.id)
        context = {
            "model": instance.reference or instance.model.modelId,
            "args": [],
            "lora_adapters": {},
            "env": [],
            "configs": [],
            "volumeMounts": {"hf_cache": {"mountPath": "/model"}},
            # The chart has no startup probe, and a first start downloads
            # the weights: minutes, which the hub library does not resume
            # after a kill. The delay applies at container start only, so
            # a server that hangs later is still restarted, and readiness
            # keeps traffic away until /health answers.
            "liveness_probe_initial_delay": LIVENESS_INITIAL_DELAY_SECONDS,
            "credential_secret_name": credential_secret_name,
            "credential_secret_key": CREDENTIAL_KEY,
        }

        tracing_url = os.environ.get("TRACING_URL")
        if (
            instance.config
            and instance.config.enable_tracing
            and not tracing_url
        ):
            self.logger.warning(
                "Tracing was asked for but TRACING_URL is not set: "
                "starting %s without it",
                instance.id,
            )
        if instance.config and instance.config.enable_tracing and tracing_url:
            if instance.config.args is None:
                instance.config.args = {}
            instance.config.args["--otlp-traces-endpoint"] = tracing_url
            instance.config.args["--collect-detailed-traces"] = os.environ.get(
                "VLLM_COLLECT_DETAILED_TRACES", "all"
            )

        if instance.config and instance.config.quantization:
            context["quantization"] = str(instance.config.quantization.lower())
            context["dtype"] = "auto"

        self.get_args(instance, context)
        self.get_env_vars(instance, context)

        # populate the argument `lora-modules` with a space separated list of adapter ids/paths
        if instance.config and instance.config.lora_adapters:
            lora_adapters = []
            for i, adapter_to_use in enumerate(
                instance.config.lora_adapters, start=1
            ):
                key = f"adapter{i}"
                if adapter_to_use.path:
                    value = f"/model/{adapter_to_use.path}".replace("//", "/")
                elif adapter_to_use.hf_id:
                    value = adapter_to_use.hf_id
                else:
                    raise ValueError(
                        f"Invalid adapter config: {adapter_to_use}"
                    )
                lora_adapters.append(f"{key}={value}")

            if len(lora_adapters) > 0:
                context["lora_adapters"] = lora_adapters
        else:
            context.pop("lora_adapters")

        return context

    async def install(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        # The rendered values reference this Secret, and it needs the
        # namespace that Helm would otherwise create later.
        await asyncio.to_thread(self.create_ns_if_needed)
        await self._ensure_hf_api_token_secret()
        await super().install(instance, engineChart)

    def get_env_vars(self, instance: InferenceInstanceSchema, context):
        env_vars = []

        # Load the default values first. The compile cache sits next to
        # the weights on the model volume, so a restart or a second launch
        # of the model skips torch.compile.
        default_env = {"VLLM_CACHE_ROOT": VLLM_CACHE_ROOT}
        if instance.engine.default_config:
            model_type = instance.model.category
            for default_config in instance.engine.default_config:
                if default_config.chart_type == model_type:
                    if default_config.name == "max_model_len":
                        context["config"]["max_model_len"] = (
                            default_config.defaultValue
                        )
                    elif default_config.name == "port":
                        context["config"]["port"] = default_config.defaultValue
                    else:
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

    def get_args(self, instance: InferenceInstanceSchema, context):
        args = []
        configs = []

        # Load the default values first
        default_args = {}
        if instance.engine.default_args:
            model_type = instance.model.category
            for default_arg in instance.engine.default_args:
                if default_arg.chart_type == model_type:
                    default_args[default_arg.name] = default_arg.defaultValue

        # Merge with instance.config.args, preferring the latter
        if instance.config and instance.config.args:
            for key, value in instance.config.args.items():
                default_args[key] = value

        # Spec 6.3: one shard per GPU unless the user set it themselves.
        if instance.gpu_count > 1 and not (
            default_args.keys()
            & {"--tensor-parallel-size", "tensor-parallel-size"}
        ):
            default_args["--tensor-parallel-size"] = str(instance.gpu_count)

        # Create the final args list
        for key, value in default_args.items():
            if key in ("max_model_len", "port"):
                configs.append(
                    {
                        "name": key,
                        "value": str(value),  # Ensure the value is a string
                    }
                )
            else:
                arg = {
                    "name": key,
                    "value": str(value),  # Ensure the value is a string
                }

                if value == "" or value is None:
                    arg.pop("value")
                args.append(arg)

        self.logger.info(f"Final args: {args}")
        context["args"] = args
        context["configs"] = configs

    def get_service_name(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        return f"{self._get_release_name(instance)}"
