"""Ollama on CPU: one server per instance, models pulled by tag."""

from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

from .base_controller import Controller


class OllamaController(Controller):
    def get_service_name(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        # The chart's fullname helper returns the release name when the
        # release contains the chart name, and "ollama-<id8>" always does,
        # so the Service is not "<release>-ollama" like the other engines.
        return self._get_release_name(instance)

    def _get_engine_specific_context(
        self,
        instance: InferenceInstanceSchema,
        engineChart: EngineChartsSchema,
    ):
        context = {
            # The serving option's reference (an Ollama tag, or a
            # hf.co/<repo>:<quant> GGUF pull) when the instance was
            # launched from one; otherwise the catalog row's modelId,
            # which is the Ollama tag itself for a pre-registry row.
            "models": [instance.reference or instance.model.modelId],
            "env": [],
        }
        if instance.config and instance.config.env_vars:
            context["env"] = [
                {"name": name, "value": str(value)}
                for name, value in instance.config.env_vars.items()
            ]
        return context
