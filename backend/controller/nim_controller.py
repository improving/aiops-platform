import base64
import os
import tempfile

import requests
from kubernetes.client.exceptions import ApiException
from kubernetes import client
from schemas.engine_charts import EngineChartsSchema
from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema

class NIMController(Controller):
    def __init__(self):
        super().__init__(namespace="nim")
    
    def _get_service_name(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        chart_name_without_version_and_extension = '-'.join(os.path.splitext(engineChart.chart_name)[0].rsplit('-', 1)[:-1])
        return f"{self._get_release_name(instance)}-{chart_name_without_version_and_extension}"

    def _get_pod_labels(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        chart_name_without_version_and_extension = '-'.join(os.path.splitext(engineChart.chart_name)[0].rsplit('-', 1)[:-1])
        return f"app.kubernetes.io/instance={self._get_release_name(instance)},app.kubernetes.io/name={chart_name_without_version_and_extension}"
    
    def _get_engine_specific_context(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        self.logger.info(f"Loading engine specific context for {engineChart.chart_name}")

        engine_specific_context = {
            "imagePullSecret": {},
            "persistence": {
                "enabled": True,
                "existingClaim": "nim-pvc"
            },
            ## TODO: Every model needs to have a nim-image field in the db. Nim controller will set the image based on the db field.
            "image": {},
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

        if engineChart.chart_name.startswith("nim-llm"):
            context = self._get_llm_chart_specific_context(instance, engineChart)
            engine_specific_context.update(context)
        else:
            context = self._get_reranking_embedding_chart_specific_context(instance, engineChart)
            self.logger.info(f"NIM Chart specific context: {context}")
            engine_specific_context.update(context)
        
        self.logger.info(f"NIM engine specific context: {engine_specific_context}")
        
        return engine_specific_context
    
    def _get_llm_chart_specific_context(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        return {
            "model": {},
        }

    def _get_reranking_embedding_chart_specific_context(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        return {
            "nemo": {
                "userID": "65534",
                "groupID": "65534"
            }
        }

    def _get_downloaded_chart_name(self, instance: InferenceInstanceSchema):
        return f"{os.path.join(tempfile.gettempdir(), self._get_release_name(instance))}.tgz"
    
    async def _add_and_update_helm_repo(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        chart_path = await self._download_chart(instance, engineChart)
        chart = await self.helm.get_chart(chart_path)
        
        return chart
    
    async def _download_chart(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        chart_url = f"{engineChart.chart_repo}/{engineChart.chart_name}"
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
        
    async def _install_image_pull_secret(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        self.logger.info(f"creating image pull secret for {engineChart.chart_name}")
        secret_name = "nvcrimagepullsecret"
        ngc_api_key = os.environ.get("NGC_API_KEY")
        if not ngc_api_key:
            raise ValueError("NGC_API_KEY environment variable is not set")
        
        secret_data = {
            ".dockerconfigjson": base64.b64encode(f"{{\"auths\":{{\"nvcr.io\":{{\"username\":\"$oauthtoken\",\"password\":\"{ngc_api_key}\"}}}}}}".encode()).decode()
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

    async def _install_ngc_api_secret(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        self.logger.info(f"creating ngc-api secret for {engineChart.chart_name}")
        secret_name = "ngc-api"
        ngc_api_key = os.environ.get("NGC_API_KEY")
        if not ngc_api_key:
            raise ValueError("NGC_API_KEY environment variable is not set")

        secret_data = {
            "NGC_API_KEY": base64.b64encode(ngc_api_key.encode()).decode(),
            "NGC_CLI_API_KEY": base64.b64encode(ngc_api_key.encode()).decode()
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

        self.logger.info(f"Installing image pull secret for {engineChart.chart_name}")

    async def install(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        await self._install_image_pull_secret(instance, engineChart)
        await self._install_ngc_api_secret(instance, engineChart)
        await super().install(instance, engineChart)
    
    async def _uninstall_secrets(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        self.logger.info(f"removing image pull secret for {engineChart.chart_name}")
        secret_names = ["nvcrimagepullsecret", "ngc-api"]

        for secret_name in secret_names:
            try:
                self.core_v1_api.delete_namespaced_secret(secret_name, self.namespace)
                self.logger.info(f"Secret '{secret_name}' deleted successfully")
            except ApiException as e:
                self.logger.exception(f"Failed to delete secret '{secret_name}': {str(e)}")
                raise
    
    async def uninstall(self, instance: InferenceInstanceSchema, engineChart: EngineChartsSchema):
        await super().uninstall(instance, engineChart)
        # TODO: check db for any nim charts installed. If there are any, then don't delete the secret.
        # await self._uninstall_secrets(instance, engineChart)

    def _unlink_downloaded_chart(self, instance: InferenceInstanceSchema):
        try:
            os.unlink(self._get_downloaded_chart_name(instance))
        except FileNotFoundError:
            self.logger.info(f"File {self._get_downloaded_chart_name(instance)} not found")
        except Exception as e:
            self.logger.exception(f"Failed to unlink downloaded chart: {str(e)}")
            raise