from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema
import kubernetes
from kubernetes import client
from pyhelm3 import Client as HelmClient
from pyhelm3.errors import ReleaseNotFoundError
from jinja2 import Environment, FileSystemLoader
import yaml
from api.kubernetes_utils import load_kubernetes_config

class VLLMController(Controller):
    def __init__(self):
        config_source = load_kubernetes_config()
        print(f"Loaded Kubernetes configuration from: {config_source}")
        self.api_instance = client.CustomObjectsApi()
        self.namespace = "ai-stack"
        self.helm = HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader('templates'))

    def _get_chart_name(self, instance: InferenceInstanceSchema):
        return f"vllm-{str(instance.model.id)[-8:]}-{str(instance.engine.id)[-8:]}-{str(instance.id)[-4:]}"
    
    def _get_service_name(self, instance: InferenceInstanceSchema):
        return f"{self._get_chart_name(instance)}"
    
    def _get_pod_labels(self, instance: InferenceInstanceSchema):
        return f"app.kubernetes.io/instance={self._get_chart_name(instance)},app.kubernetes.io/name=vllm"

    async def _prepare_helm_values(self, instance: InferenceInstanceSchema):
        template = self.jinja_env.get_template('vllm-values.yaml.jinja')
        
        context = {
            "model": instance.model.modelId,
            # "servedModelName": instance.model.modelId,
            "image": {},
            "service": {
                "type": "LoadBalancer",
            },
            "env": {},
            # Add empty objects for non-leaf parameters
            "readManyPVC": {
                "accessModes": [],
            },
            "resources": {
                "requests": {},
                "limits": {},
            },
            "volumes": {
                "hf_cache": {
                    "claimName": "hf-cache"
                }
            },
            "volumeMounts": {
                "hf_cache": {
                    "mountPath": "/model"  # has to be /model to match the image (local image path)
                }
            }
        }

        if instance.config and instance.config.quantization:
            context["quantization"] = str(instance.config.quantization.lower())
            context["dtype"] = "auto"
        
        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        print(f"vllm values: {values}")
        
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
                chart_name,
                chart,
                values,
                namespace=self.namespace,
                create_namespace=True
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
                chart_name,
                chart,
                values,
                namespace=self.namespace
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