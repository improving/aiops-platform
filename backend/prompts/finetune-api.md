# Finetune API

## Overview
I want to add support for a new API that will enable CRUD operations on finetune jobs. The finetune jobs will run a kubernetes batch job to finetune a model.

## Finetune Object DB model
The finetune object will be stored in a relational db using SQLAlchemy ORM. The schema of the finetune object should be as follows:
- id: uuid (primary key, auto-generated, optional)
- name: string (required)
- model: string (required)
- params: jsonb (required)
- status: string (required)
- logs: string (optional)
- createdAt: datetime (required)
- updatedAt: datetime (required)

## Finetune Object pydantic schema
The pydantic schema for the finetune object should be as follows:
- id: uuid (primary key, auto-generated, optional)
- name: string (required)
- model: string (required)
- params: jsonb (required)
- status: string (required)
- logs: string (optional)
- createdAt: datetime (required)
- updatedAt: datetime (required)

## Requirements
The requirements for the api are in two parts.
1. Implementing the CRUD API for the finetune object.
2. Implementing the API to interact with the kubernetes batch job.

### CRUD API Implementation
1. The new API should be able to list all the finetune jobs available in the cluster.
2. The new API should be able to create a new finetune job. On creation, the finetune job should be created on the underlying kubernetes cluster.
3. The new API should be able to delete a finetune job. On deletion, the finetune job should be deleted from the underlying kubernetes cluster.
4. The new API should be able to get the details of a finetune job.
5. The new API should be able to update a finetune job. On update, the finetune job should be updated on the underlying kubernetes cluster.

#### Rules for the CRUD API
- The CRUD API should be implemented using FastAPI framework.
- The CRUD API should be implemented in a new file in the `api` directory.
- The DB model should be implemented in a new file in the `models` directory.
- The pydantic schema should be implemented in a new file in the `schemas` directory.
- The repository should be implemented in a new file in the `repositories` directory.
- The api file should declare a router at the beginning, which MUST be included in the `app.py` file.

### API to interact with the kubernetes batch job Implementation
1. The business logic to create/delete the kubernetes batch job should be implemented in the `controllers` package in a new file.
2. This file must have a function `submit_job` which takes in a finetune object and submits the kubernetes batch job, and a function `delete_job` which takes in a finetune object and deletes the kubernetes batch job.
3. The Kubernetes batch job should have:
    - A job name as `finetune-job-<finetune-job-id-first-8-characters>`.
    - A job image `infracloudio/tf-training-mnist:latest` which is the docker image to use for the job.
    - A job command `autotrain --config /job/config/conf.yaml` which is the command to run for the job.
    - The `conf.yaml` should have the json in the `params` specified of the finetune object converted to yaml format.
    - This `conf.yaml` file needs to be placed in a configmap named `autotrain-configmap` in the same namespace as the job & needs to be mounted as a volume to the job at `/job/config/conf.yaml`.
    - The job should have 1 replica.
    - The job should have 1 gpu with 1000 milli-cores.
    - The job should have a restart policy of `Never`.
    - The job should have a service account named `finetune-job-sa`.
    - The job should mount pvc named `hf-cache` to `/data`.
    - It should have a volume named `shm` of type `emptyDir` and size `2Gi`.
    - It should have following labels:
      - `app.kubernetes.io/name: finetune-job`
      - `app.kubernetes.io/instance-id: <finetune-job-id>`
      - `app.kubernetes.io/component: finetune-job`
      - `app.kubernetes.io/managed-by: aiops`


#### Rules for the kubernetes batch job
- The kubernetes batch job controller should be implemented as a class.
- The class should have methods to submit the job, delete the job, get the job status and logs.
- The class should contain all the required variables to be used by the methods. Such as listed below. Feel free to add more variables if needed.
  - namespace: string (optional, default: ai-stack)
  - kubernetes_job_client: kubernetes Job client (Name: client)
  - logger: logger object (from logger.py)
- The class should also have utility functions to get the job name, labels

## General rules to follow other than the specific ones mentioned above
- Always place components in the correct folder.
- Focus on readability over being performant.
- MUST HAVE: Fully implement all requested functionality.
- Leave NO todo’s, placeholders or missing pieces.
- Ensure code is complete! Verify thoroughly finalized.
- Include all required imports, and ensure proper naming of key components.
- Be concise. Minimize any other prose.
- Write concise, readable and technical python code with accurate examples.
- Prefer iteration and modularization over code duplication.
- Use descriptive variable names with auxiliary verbs (e.g., isLoading, hasError).
- All functions must have a docstring, explaining the function in detail.
- The docstring for fastapi router functions should explain the parameters, the return type and the possible exceptions.
- Always use type hints for all functions.
- MUST HAVE: Always write unit tests for all functions in `tests` directory.
- The unit test file should be named as `<file-name>_test.py`.
- MUST HAVE: Write unique, diverse, and intuitive unit tests for functions.
- ALWAYS TEST FOR EXCEPTIONS!
- ALWAYS TEST FOR CORNER CASES!
- ALWAYS TEST FOR BOUNDARY VALUES!
- ALWAYS TEST FOR ERRORS!
- ALWAYS TEST FOR EDGE CASES!
- ALWAYS TEST FOR NULL VALUES!
- ALWAYS TEST FOR EMPTY VALUES!
- ALWAYS TEST FOR ZERO VALUES!
