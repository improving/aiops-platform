from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema
import kubernetes
from kubernetes import client, config
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError
import os
import base64

class TGIController(Controller):
    def __init__(self):
        config.load_kube_config()
        self.api_instance = client.CustomObjectsApi()
        self.core_v1_api = client.CoreV1Api()
        self.namespace = "tgi"
        self.helm = HelmClient()

    def _get_chart_name(self, instance: InferenceInstanceSchema):
        return f"tgi-{str(instance.model.id)[-8:]}-{str(instance.engine.id)[-8:]}-{str(instance.id)[-4:]}"

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
            print(f"Secret '{secret_name}' created successfully")
        except kubernetes.client.exceptions.ApiException as e:
            if e.status == 409:
                print(f"Secret '{secret_name}' already exists")
            else:
                raise

    async def _prepare_helm_values(self, instance: InferenceInstanceSchema):
        # Prepare the values to be passed to the Helm chart
        env_values = [
            {"name": "MAX_INPUT_LENGTH", "value": str(instance.config.maxInputLength)} if instance.config and instance.config.maxInputLength else [],
            {"name": "MAX_TOTAL_TOKENS", "value": str(instance.config.maxTokens)} if instance.config and instance.config.maxTokens else  [],
            {"name": "MAX_BATCH_PREFILL_TOKENS", "value": str(instance.config.maxBatchPrefillTokens)} if instance.config and instance.config.maxBatchPrefillTokens else  [],
            {"name": "MAX_BATCH_TOTAL_TOKENS", "value": str(instance.config.maxBatchTotalTokens)} if instance.config and instance.config.maxBatchTotalTokens else  [],
            {"name": "QUANTIZATION", "value": instance.config.quantization} if instance.config and instance.config.quantization else  [],
            {
                "name": "HF_API_TOKEN",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": "hf-api-token",
                        "key": "HF_API_TOKEN"
                    }
                }
            }
        ]
        env_values = [value for value in env_values if value]

        values = {
            "config": {
                "modelID": str(instance.model.modelId)
            },
            "env": env_values,
            "service": {
                "type": "LoadBalancer",
                "port": 80
            },
            "volumes": [
                {
                    "name": "hf-cache",
                    "persistentVolumeClaim": {
                        "claimName": "hf-cache"
                    }
                }
            ],
            "volumeMounts": [
                {
                    "name": "hf-cache",
                    "mountPath": "/data"
                }
            ]
        }
        return values

    async def _add_and_update_helm_repo(self, instance: InferenceInstanceSchema):
        repo_url = instance.engine.helm_chart_repo
        chart_name = instance.engine.helm_chart_name

        chart = await self.helm.get_chart(chart_name, repo = repo_url)
        print(f"fetched chart: {chart_name} from {repo_url}")
        
        return chart

    async def install(self, instance: InferenceInstanceSchema):
        print(f"instance inside tgi_controller: {instance}")
        await self._create_hf_api_token_secret()
        chart = await self._add_and_update_helm_repo(instance)
        
        chart_name = self._get_chart_name(instance)
        values = await self._prepare_helm_values(instance)
        
        try:
            await self.helm.install_or_upgrade_release(
                chart_name,
                chart,
                values,
                namespace=self.namespace,
                create_namespace=True,
            )
            print(f"Helm install succeeded for chart: {chart_name}")
        except Exception as e:
            raise Exception(f"Helm install failed: {str(e)}")

    async def upgrade(self, instance: InferenceInstanceSchema):
        chart = await self._add_and_update_helm_repo(instance)
        
        chart_name = self._get_chart_name(instance)
        # values = await self._prepare_helm_values(instance)
        
        try:
            await self.helm.install_or_upgrade_release(
                release_name=chart_name,
                chart=chart,
                namespace=self.namespace,
                reuse_values=True,
                # values=values
            )
            print(f"Helm upgrade succeeded for chart: {chart_name}")
        except Exception as e:
            raise Exception(f"Helm upgrade failed: {str(e)}")

    async def remove(self, instance: InferenceInstanceSchema):
        chart_name = self._get_chart_name(instance)
        
        try:
            revision = await self.helm.get_current_revision(chart_name, namespace=self.namespace)
            print(f"Current revision: {revision}")
            await revision.release.uninstall(wait=True)
            print(f"Helm uninstall succeeded for chart: {chart_name}")
        except ReleaseNotFoundError:
            print(f"Release not found: {chart_name}")
        except Exception as e:
            # print error with traceback
            import traceback
            traceback.print_exc()
            raise Exception(f"Helm uninstall failed: {str(e)}")