from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class VLLMController(Controller):

    def _get_engine_specific_context(self, instance: InferenceInstanceSchema,
                                     engineChart: EngineChartsSchema):
        context = {
            "model": instance.model.modelId,
            "args": [],
            "lora_adapters": {},
            "env": [],
            "configs": [],
            "volumeMounts": {
                "hf_cache": {
                    "mountPath": "/model"
                }
            }
        }

        if instance.config and instance.config.quantization:
            context["quantization"] = str(instance.config.quantization.lower())
            context["dtype"] = "auto"

        self.get_args(instance, context)
        self.get_env_vars(instance, context)

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
                context["lora_adapters"] = lora_adapters
        else:
            context.pop("lora_adapters")

        return context

    def get_env_vars(self, instance: InferenceInstanceSchema, context):
        env_vars = []

        # Load the default values first
        default_env = {}
        if instance.engine.default_config:
            model_type = instance.model.category
            for default_config in instance.engine.default_config:
                if default_config.chart_type == model_type:
                    if default_config.name == "max_model_len":
                        context["config"][
                            "max_model_len"] = default_config.defaultValue
                    elif default_config.name == "port":
                        context["config"]["port"] = default_config.defaultValue
                    else:
                        default_env[
                            default_config.name] = default_config.defaultValue

        # Merge with instance.config.env_vars, preferring the latter
        if instance.config and instance.config.env_vars:
            for key, value in instance.config.env_vars.items():
                default_env[key] = value

        # Create the final env_vars list
        for key, value in default_env.items():
            env_vars.append({
                "name": key,
                "value": str(value)  # Ensure the value is a string
            })

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

        # Create the final args list
        for key, value in default_args.items():
            if key in ('max_model_len', 'port'):
                configs.append({
                    "name": key,
                    "value": str(value)  # Ensure the value is a string
                })
            else:
                args.append({
                    "name": key,
                    "value": str(value)  # Ensure the value is a string
                })

        self.logger.info(f"Final args: {args}")
        context["args"] = args
        context["configs"] = configs

    def get_service_name(self, instance: InferenceInstanceSchema,
                         engineChart: EngineChartsSchema):
        return f"{self._get_release_name(instance)}"
