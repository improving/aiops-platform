# New API support for Kubeflow notebooks

## Overview
I want to add support for a new API that will enable CRUD operations on Kubeflow notebooks. The Kubeflow notebooks can be installed using `kf-notebooks` helm chart from `https://infracloudio.github.io/charts` repo.

## Requirements
1. The new API should be able to list all the notebooks available in the cluster.
2. The new API should be able to create a new notebook. On creation, the notebook should be created on the underlying kubernetes cluster.
3. The new API should be able to delete a notebook. On deletion, the notebook should be deleted from the underlying kubernetes cluster.
4. The new API should be able to get the details of a notebook.
5. The new API should be able to update a notebook. On update, the notebook should be updated on the underlying kubernetes cluster.

## Implementation
- The new API should be implemented as a RESTful API. The API should be implemented using FastAPI framework, in accordance with the currently existing API implementation. The existing APIs are defined in `api` directory. The new API should be defined in a new file in the `api` directory.
- The notebooks object should be stored in relational db using SQLAlchemy ORM. The schema of the notebooks object should be as follows:
  - id: uuid (primary key, auto-generated, optional)
  - name: string (required)
  - type: string  # valid values: jupyter/vscode/rstudio (required)
  - framework: string  # valid values: tensorflow/pytorch (required)
  - nvidia_gpu: boolean  # whether the notebook has nvidia gpu (required)
  - image: string  # the docker image to use for the notebook (optional)
  - resources:
    - cpu: string (optional)
    - memory: string (optional)
    - gpu: string (optional)
  - storageSize: string (optional)
  - service:
    - type: string (optional)
    - port: int (optional)
  - status: string (optional)
  - endpoint: string (optional)
  - createdAt: datetime (optional)
  - updatedAt: datetime (optional)
- The DB schema should be created in the `models` directory. The db schema should not contain `status` field.
- The values for the properties under resources, service should be flattened as `resources.cpu` and `service.type` etc. while storing in the database.
- The API endpoints should validate the input values for type, framework, nvidia_gpu to ensure that they are valid.
- The get/list apis should return the list of all the notebooks in the cluster, along with their status. The status should be populated dynamically every time the get/list api is called, using the `kubernetes-utils.py` utility functions.
- The request response schema for the notebook object should be defined in the `schemas` directory.
- The values file for kf-notebooks helm chart is present in `chart-values/kf-notebooks-values.yaml` file. This file should be used to create a jinja template for the notebook object under `templates` directory.
- The helm chart installation should be handled by the `notebooks-controller.py` file, which should be created in the `controllers` directory. The `vectordb-controler.py` file should be used for reference.
- The `notebooks-controller.py` should use the `kf-notebooks-values.yaml.jinja` template to create the notebook object.
- The `notebooks-controller.py` should be able to perform the CRUD operations on the notebook object.
- The `notebooks-controller.py` should be able to get the status of the notebook from the underlying kubernetes cluster.
- The `notebooks-controller.py` should be able to get the endpoint of the notebook from the underlying kubernetes cluster.
- The `notebooks-controller.py` should be able to delete the notebook from the underlying kubernetes cluster.

## Directory structure
- `api` - for api implementation
- `controllers` - for controllers responsible for helm chart CRUD operations
- `db` - for database
- `models` - for models
- `schemas` - for schemas
- `templates` - for templates
- `utils` - for utility functions

## Rules
- The `id` field should be generated using `uuid.uuid4()` and should be a string.
- The `createdAt` and `updatedAt` fields should be generated using `datetime.now()` and should be in `YYYY-MM-DD HH:MM:SS` format.
- The `status` field should be populated using the `kubernetes-utils.py` utility functions.
- The `endpoint` field should be populated using the `kubernetes-utils.py` utility functions, by a scheduled job, like the one in `vectordb-controller.py` file.




