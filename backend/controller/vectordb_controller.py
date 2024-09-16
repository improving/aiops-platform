
from controller.base_controller import Controller
from schemas.engine_charts import EngineChartsSchema
from schemas.inference_instance import InferenceInstanceSchema

class VectorDBController(Controller):
    def _get_engine_specific_context(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        return {}
    def _get_service_name(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        return f"{self._get_release_name(instance)}"