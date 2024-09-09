import os
import subprocess
import yaml
import tempfile
import requests
from .base_controller import Controller
from schemas.inference_instance import InferenceInstanceSchema
import kubernetes
from kubernetes import client
from pyhelm3 import Client as HelmClient
from pyhelm3 import Chart
from pyhelm3.errors import ReleaseNotFoundError
from jinja2 import Environment, FileSystemLoader
from api.kubernetes_utils import load_kubernetes_config

class NIMController(Controller):
    def __init__(self):
        config_source = load_kubernetes_config()
        print(f"Loaded Kubernetes configuration from: {config_source}")
        self.api_instance = client.CustomObjectsApi()
        self.namespace = "nim"
        self.helm = HelmClient()
        self.jinja_env = Environment(loader=FileSystemLoader('templates'))

    def _get_chart_name(self, instance: InferenceInstanceSchema):
        return f"nim-{str(instance.model.id)[-8:]}-{str(instance.engine.id)[-8:]}-{str(instance.id)[-4:]}"
    
    def _get_service_name(self, instance: InferenceInstanceSchema):
        return f"{self._get_chart_name(instance)}-nim-llm"

    def _get_pod_labels(self, instance: InferenceInstanceSchema):
        return f"app.kubernetes.io/instance={self._get_chart_name(instance)},app.kubernetes.io/name=nim-llm"

    async def _prepare_helm_values(self, instance: InferenceInstanceSchema):
        template = self.jinja_env.get_template('nim-llm-values.yaml.jinja')
        
        context = {
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
            "service": {
                "type": "LoadBalancer",
                "port": 80
            },
            "metrics": {
                "enabled": True,
                "serviceMonitor": {
                    "enabled": True,
                    "additionalLabels": {
                        "release": "prometheus"
                    }
                }
            },
            "resources": {
                "limits": {
                    "gpu": 1
                },
                "requests": {
                    "gpu": 1
                }
            },
            "nodeSelector": {
                "hostname": instance.host
            }
        }
        
        rendered_yaml = template.render(context)
        values = yaml.safe_load(rendered_yaml)
        print(f"nim values: {values}")
        return values

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
            raise Exception(f"Failed to download chart: {response.status_code} {response.text}")

        with tempfile.NamedTemporaryFile(delete=False, suffix='.tgz') as temp_file:
            temp_file.write(response.content)
            return temp_file.name

    async def install(self, instance: InferenceInstanceSchema):
        print(f"instance inside nim_controller: {instance}")
        chart_path = await self._download_chart(instance)
        chart = await self.helm.get_chart(chart_path)
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
        finally:
            os.unlink(chart_path)  # Clean up the temporary file

    async def upgrade(self, instance: InferenceInstanceSchema):
        chart_path = await self._download_chart(instance)
        chart_name = self._get_chart_name(instance)
        values = await self._prepare_helm_values(instance)
        
        try:
            await self.helm.install_or_upgrade_release(
                chart_name,
                chart_path,
                values,
                namespace=self.namespace
            )
            print(f"Helm upgrade succeeded for chart: {chart_name}")
        except Exception as e:
            raise Exception(f"Helm upgrade failed: {str(e)}")
        finally:
            os.unlink(chart_path)  # Clean up the temporary file

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
            import traceback
            traceback.print_exc()
            raise Exception(f"Helm uninstall failed: {str(e)}")