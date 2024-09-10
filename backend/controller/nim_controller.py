import os
import tempfile

import requests
from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema

class NIMController(Controller):
    def __init__(self):
        super().__init__(namespace="nim")

    def _get_engine_specific_context(self, instance: InferenceInstanceSchema):
        return {
            "model": {
                "ngcAPISecret": "ngc-api-nim-llm",
                "ngcAPIKey": os.environ.get("NGC_API_KEY", os.environ.get("NGC_API_TOKEN"))
            },
            "persistence": {
                "enabled": True,
                "existingClaim": "nim-pvc"
            },
            "image": {
                "repository": instance.config.image.split(":")[0] if instance.config and instance.config.image else "nvcr.io/nim/meta/llama3-8b-instruct",
                "tag": instance.config.image.split(":")[1] if instance.config and instance.config.image and ":" in instance.config.image else "1.0.3"
            },
            "metrics": {
                "enabled": True,
                "serviceMonitor": {
                    "enabled": True,
                    "additionalLabels": {
                        "release": "prometheus"
                    }
                }
            }
        }

    def _get_downloaded_chart_name(self, instance: InferenceInstanceSchema):
        return f"{os.path.join(tempfile.gettempdir(), self._get_chart_name(instance))}.tgz"
    
    async def _add_and_update_helm_repo(self, instance: InferenceInstanceSchema):
        chart_path = self._download_chart(instance)
        chart = await self.helm.get_chart(chart_path)
        
        return chart
    
    async def _download_chart(self, instance: InferenceInstanceSchema):
        chart_url = f"{instance.engine.helm_chart_repo}/{instance.engine.helm_chart_name}"
        ngc_api_key = os.environ.get("NGC_API_KEY")
        if not ngc_api_key:
            raise ValueError("NGC_API_KEY environment variable is not set")

        headers = {
            "Authorization": f"Bearer {ngc_api_key}"
        }

        response = requests.get(chart_url, headers=headers)
        if response.status_code != 200:
            self.logger.error(f"Failed to download chart: {response.status_code} {response.text}")
            raise Exception(f"Failed to download chart: {response.status_code} {response.text}")

        with tempfile.NamedTemporaryFile(delete=False, suffix='.tgz') as temp_file:
            temp_file.write(response.content)
            new_chart_name = self._get_downloaded_chart_name(instance)
            os.rename(temp_file.name, new_chart_name)
            return new_chart_name

    def _unlink_downloaded_chart(self, instance: InferenceInstanceSchema):
        os.unlink(self._get_downloaded_chart_name(instance))