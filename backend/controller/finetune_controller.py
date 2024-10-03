import yaml
from kubernetes import client

from logger import setup_logger
from schemas.finetune import Finetune
from utils.kubernetes_utils import (create_config_map, delete_config_map,
                                    delete_job, get_job_logs, get_job_status,
                                    submit_job)

logger = setup_logger(__name__)


class FinetuneController:

    def __init__(self):
        self.namespace = "ai-stack"

    def get_job_name(self, finetune: Finetune) -> str:
        return f"finetune-job-{str(finetune.id)[:8]}"

    def get_job_labels(self, finetune: Finetune) -> dict:
        return {
            "app.kubernetes.io/name": "finetune-job",
            "app.kubernetes.io/instance-id": str(finetune.id),
            "app.kubernetes.io/component": "finetune-job",
            "app.kubernetes.io/managed-by": "aiops"
        }

    async def submit_job(self, finetune: Finetune):
        job_name = self.get_job_name(finetune)
        labels = self.get_job_labels(finetune)

        # Create ConfigMap
        config_map_name = f"{job_name}-config"
        config_data = yaml.dump(finetune.params)
        config_map = client.V1ConfigMap(metadata=client.V1ObjectMeta(
            name=config_map_name, namespace=self.namespace),
                                        data={"conf.yaml": config_data})
        create_config_map(self.namespace, config_map)

        # Create Job
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name,
                                         namespace=self.namespace,
                                         labels=labels),
            spec=client.V1JobSpec(template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="finetune",
                            image="huggingface/autotrain-advanced:ed8e0c1",
                            # image="python:slim",
                            command=[
                                "autotrain", "--config",
                                "/job/config/conf.yaml"
                            ],
                            # command=[
                            #     "python3", "-c",
                            #     "import time; start_time = time.time(); while time.time() - start_time < 300: print('hello'); time.sleep(5)"
                            # ],
                            resources=client.V1ResourceRequirements(
                                requests={"nvidia.com/gpu": "1"},
                                limits={
                                    "nvidia.com/gpu": "1",
                                    "cpu": "1"
                                }),
                            volume_mounts=[
                                client.V1VolumeMount(name="config",
                                                     mount_path="/job/config"),
                                client.V1VolumeMount(name="hf-cache",
                                                     mount_path="/data"),
                                client.V1VolumeMount(name="shm",
                                                     mount_path="/dev/shm")
                            ])
                    ],
                    restart_policy="Never",
                    service_account_name="finetune-job-sa",
                    volumes=[
                        client.V1Volume(
                            name="config",
                            config_map=client.V1ConfigMapVolumeSource(
                                name=config_map_name)),
                        client.V1Volume(name="hf-cache",
                                        persistent_volume_claim=client.
                                        V1PersistentVolumeClaimVolumeSource(
                                            claim_name="hf-cache")),
                        client.V1Volume(
                            name="shm",
                            empty_dir=client.V1EmptyDirVolumeSource(
                                medium="Memory", size_limit="2Gi"))
                    ]))))

        submit_job(self.namespace, job)

    async def delete_job(self, finetune: Finetune):
        job_name = self.get_job_name(finetune)
        config_map_name = f"{job_name}-config"

        # Delete Job
        delete_job(self.namespace, job_name)

        # Delete ConfigMap
        delete_config_map(self.namespace, config_map_name)
        logger.info(f"ConfigMap {config_map_name} deleted successfully")

    async def get_job_status(self, finetune: Finetune):
        job_name = self.get_job_name(finetune)
        job_status = await get_job_status(job_name, self.namespace)
        return job_status

    async def get_job_logs(self, finetune: Finetune):
        job_name = self.get_job_name(finetune)
        job_logs = await get_job_logs(job_name, self.namespace)
        return job_logs
