from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema
import kubernetes
from kubernetes import client, config
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError
from jinja2 import Environment, FileSystemLoader
import yaml

class VLLMController(Controller):
    def __init__(self):
        config.load_kube_config()
        self.api_instance = client.CustomObjectsApi()
        self.namespace = "vllm"
        self.helm = HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader('templates'))

    def _get_chart_name(self, instance: InferenceInstanceSchema):
        return f"vllm-{str(instance.model.id)[-8:]}-{str(instance.engine.id)[-8:]}-{str(instance.id)[-4:]}"

    async def _prepare_helm_values(self, instance: InferenceInstanceSchema):
        template = self.jinja_env.get_template('vllm-values.yaml.jinja')
        
        # Prepare the context for the template
        context = {
            "model": instance.model.modelId,
            "servedModelName": instance.model.name,
            "quantization": instance.config.quantization if instance.config else "",
            "maxModelLen": instance.config.maxTokens if instance.config else "",
            "image": {
                "repository": instance.config.image.split(":")[0] if instance.config and instance.config.image else "",
                "tag": instance.config.image.split(":")[1] if instance.config and instance.config.image and ":" in instance.config.image else "latest"
            },
            "env": [
                {"name": "MODEL_ID", "value": str(instance.model.id)},
                {"name": "MAX_INPUT_LENGTH", "value": str(instance.config.maxInputLength) if instance.config else ""},
                {"name": "MAX_TOTAL_TOKENS", "value": str(instance.config.maxTokens) if instance.config else ""},
                {"name": "MAX_BATCH_PREFILL_TOKENS", "value": str(instance.config.maxBatchPrefillTokens) if instance.config else ""},
                {"name": "MAX_BATCH_TOTAL_TOKENS", "value": str(instance.config.maxBatchTotalTokens) if instance.config else ""},
            ],
            "service": {
                "type": "ClusterIP",
                "port": 8080
            },
            "ingress": {
                "enabled": True,
                "hosts": [{"host": instance.host, "paths": [{"path": "/", "pathType": "ImplementationSpecific"}]}]
            }
        }
        
        # Render the template
        rendered_yaml = template.render(context)
        
        # Parse the rendered YAML
        values = yaml.safe_load(rendered_yaml)
        print(f"values: {values}")
        
        return values

    async def _add_and_update_helm_repo(self, instance: InferenceInstanceSchema):
        repo_url = instance.engine.helm_chart_repo
        chart_name = instance.engine.helm_chart_name

        chart = await self.helm.get_chart(chart_name, repo = repo_url)
        print(f"fetched chart: {chart_name} from {repo_url}")
        
        return chart

    async def install(self, instance: InferenceInstanceSchema):
        print(f"instance inside vllm_controller: {instance}")
        chart = await self._add_and_update_helm_repo(instance)
        
        chart_name = self._get_chart_name(instance)
        values = await self._prepare_helm_values(instance)
        
        try:
            await self.helm.install_or_upgrade_release(
                release_name=chart_name,
                chart=chart,
                namespace=self.namespace,
                create_namespace=True,
                values=values
            )
            print(f"Helm install succeeded for chart: {chart_name}")
        except Exception as e:
            raise Exception(f"Helm install failed: {str(e)}")

    async def upgrade(self, instance: InferenceInstanceSchema):
        chart = await self._add_and_update_helm_repo(instance)
        
        chart_name = self._get_chart_name(instance)
        values = await self._prepare_helm_values(instance)
        
        try:
            await self.helm.install_or_upgrade_release(
                release_name=chart_name,
                chart=chart,
                namespace=self.namespace,
                values=values
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