import asyncio
import json
import os
import pprint
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_
from sqlalchemy.orm import Session

from api.inference_status import (
    _engine_chart_for,
    _engine_chart_query,
    check_pod_status_and_readiness,
)
from auth.current_user import CurrentUser, get_current_user, require_writer
from auth.policy import authorize_read, authorize_write, org_scope
from controller import get_controller
from db.database import get_db
from logger import setup_logger
from models.engine_chart_dashboards import DBEngineChartDashboards
from models.engine_charts import DBEngineCharts
from models.engines import DBEngine
from models.inference_instance import (
    DBInferenceInstance,
    DBInferenceInstanceConfigParams,
)
from models.inference_instance_dashboards import DBInferenceInstanceDashboards
from models.model_adapters import DBModelAdapters
from models.models import DBModel
from models.serving_option import ServingOption
from schemas.inference_instance import (
    InferenceInstanceCreateSchema,
    InferenceInstanceSchema,
)
from schemas.inference_instance_dashboards import (
    InferenceInstanceDashboardsSchema,
)
from utils import genid
from utils.credentials import (
    delete_credential,
    find_credential,
    generate_secret,
    store_credential,
)
from utils.gateway import GatewayPolicyError
from utils.instance_status import (
    READ_ONLY_STATUS_FIELDS,
    STATUS_FAILED,
    STATUS_PENDING,
    mark_failed,
)
from utils.kubernetes_utils import get_default_namespace
from utils.litellm import (
    LiteLLMError,
    instance_litellm_params,
    instance_model_name,
)
from utils.litellm import (
    get_client as get_litellm_client,
)

# The kind tag for utils/credentials.py: one API key per inference instance.
CREDENTIAL_KIND = "inf"

# Engines that pull their models themselves, without a Hugging Face token
# (every other engine's chart reads the hf-api-token Secret).
NO_HF_TOKEN_ENGINES = {"ollama"}

router = APIRouter()

# Initialize the logger
logger = setup_logger(__name__)

# Grafana's organization id, the same for every dashboard. Not the
# tenancy org_id column on the instance rows.
GRAFANA_ORG_ID = "1"


def register_instance(
    db, db_instance, full_instance, engine_chart, controller, api_key
):
    """Best effort: a LiteLLM outage never fails a launch."""
    litellm = get_litellm_client()
    if litellm is None or engine_chart is None:
        return
    route = instance_litellm_params(
        full_instance.engine.name,
        full_instance.model.category,
        full_instance.reference or full_instance.model.modelId,
        controller.service_url(full_instance, engine_chart),
        api_key,
    )
    if route is None:
        logger.info(
            f"no LiteLLM route for "
            f"{full_instance.engine.name}/{full_instance.model.category}"
        )
        return
    params, info = route
    info["aiops_instance_id"] = str(db_instance.id)
    name = instance_model_name(db_instance.id)
    try:
        model_id = litellm.register_model(name, params, info)
    except LiteLLMError as e:
        logger.error(f"LiteLLM registration failed for {name}: {e}")
        return
    db_instance.litellm_model_name = name
    db_instance.litellm_model_id = model_id
    db.commit()


def unregister_instance(db_instance):
    litellm = get_litellm_client()
    if litellm is None or not db_instance.litellm_model_id:
        return
    try:
        litellm.delete_model(db_instance.litellm_model_id)
    except LiteLLMError as e:
        logger.error(
            f"LiteLLM unregistration failed for "
            f"{db_instance.litellm_model_name}: {e}"
        )


async def _uninstall_best_effort(controller, full_instance):
    """A half-created release must not linger next to a Failed row."""
    try:
        await controller.uninstall(full_instance)
    except Exception:
        logger.exception(
            "Failed to uninstall the release of %s after a failed install",
            full_instance.id,
        )


@router.get(
    "/v1alpha1/inferenceInstance", response_model=list[InferenceInstanceSchema]
)
async def list_inference_instances(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    List the inference instances of the caller's organization.

    Args:
        db (Session): The database session, injected by FastAPI.

    Returns:
        List[InferenceInstanceSchema]: A list of all inference instances.

    Raises:
        HTTPException: If there's an error retrieving the inference instances.
    """
    try:
        instances = (
            db.query(DBInferenceInstance)
            .filter(org_scope(DBInferenceInstance, user))
            .all()
        )
        for instance in instances:
            instance.ready, _ = check_pod_status_and_readiness(instance, db)
        return instances
    except Exception as e:
        logger.exception(f"Error in list_inference_instances: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstanceSchema
)
async def get_inference_instance(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Retrieve a specific inference instance by ID.

    Args:
        id (uuid.UUID): The ID of the inference instance to retrieve.

    Returns:
        InferenceInstanceSchema: The requested inference instance.

    Raises:
        HTTPException: If the inference instance is not found or there's an internal error.
    """
    try:
        instance = (
            db.query(DBInferenceInstance)
            .filter(DBInferenceInstance.id == id)
            .first()
        )
        if not instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(
                status_code=404, detail="Inference instance not found"
            )
        authorize_read(user, instance, "inference instance")

        instance.ready, _ = check_pod_status_and_readiness(instance, db)

        return instance
    except HTTPException:
        logger.exception("HTTPException in get_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in get_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/v1alpha1/inferenceInstance/{id}/dashboards",
    response_model=list[InferenceInstanceDashboardsSchema],
)
async def get_inference_instance_dashboards(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Retrieve dashboards for a specific inference instance.

    Args:
        id (uuid.UUID): The ID of the inference instance.

    Returns:
        List[InferenceInstanceDashboardsSchema]: A list of dashboards associated with the inference instance.

    Raises:
        HTTPException: If there's an error retrieving the dashboards.
    """
    try:
        instance = (
            db.query(DBInferenceInstance)
            .filter(DBInferenceInstance.id == id)
            .first()
        )
        if not instance:
            raise HTTPException(
                status_code=404, detail="Inference instance not found"
            )
        authorize_read(user, instance, "inference instance")

        db_instance_dashboards = (
            db.query(DBInferenceInstanceDashboards)
            .filter(DBInferenceInstanceDashboards.inference_instance_id == id)
            .all()
        )

        if not db_instance_dashboards:
            return []

        instance_dashboard_list = []
        for db_instance_dashboard in db_instance_dashboards:
            instance_dashboard = InferenceInstanceDashboardsSchema(
                id=db_instance_dashboard.id,
                org_id=db_instance_dashboard.org_id,
                query_params=json.loads(db_instance_dashboard.query_params),
            )
            chart_dashboard = (
                db.query(DBEngineChartDashboards)
                .filter(
                    DBEngineChartDashboards.id
                    == db_instance_dashboard.engine_chart_dashboard_id
                )
                .first()
            )
            if chart_dashboard:
                instance_dashboard.dashboard_id = chart_dashboard.dashboard_id
                instance_dashboard.dashboard_name = (
                    chart_dashboard.dashboard_name
                )
                instance_dashboard.panel_id = chart_dashboard.panel_id
                instance_dashboard.panel_name = chart_dashboard.panel_name
            instance_dashboard_list.append(instance_dashboard)

        return instance_dashboard_list
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            f"Error in get_inference_instance_dashboards: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


def _find_instance(
    db: Session, id: uuid.UUID, user: CurrentUser
) -> DBInferenceInstance:
    instance = (
        db.query(DBInferenceInstance)
        .filter(DBInferenceInstance.id == id)
        .filter(org_scope(DBInferenceInstance, user))
        .first()
    )
    if not instance:
        raise HTTPException(
            status_code=404, detail="Inference instance not found"
        )
    return instance


def _record_window(config_data: dict, engine, model) -> None:
    """Write the vLLM engine default for ``max_model_len`` into the
    instance's own arguments when the request names none.

    The form sends only what the user changed, and the controller merges
    the engine defaults at every render, so an instance without the
    argument follows the default of the day: its window would change on
    its next restart after the seed changes, and nothing on the row says
    what it serves. With the value on the row, the instance keeps it and
    the chat page can show it (``api.chat.instance_context_length``)."""
    if engine.name != "vLLM":
        return
    args = dict(config_data.get("args") or {})
    if "max_model_len" in args:
        return
    for default in engine.default_args or []:
        if (
            default.name == "max_model_len"
            and default.chart_type == model.category
        ):
            args["max_model_len"] = default.defaultValue
            config_data["args"] = args
            return


@router.post(
    "/v1alpha1/inferenceInstance",
    response_model=InferenceInstanceSchema,
    status_code=201,
)
async def create_inference_instance(
    instance: InferenceInstanceCreateSchema,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_writer),
):
    """
    Create a new inference instance.

    Args:
        instance (InferenceInstanceCreateSchema): The inference instance data.

    Returns:
        InferenceInstanceSchema: The created inference instance.

    Raises:
        HTTPException: If there's an error creating the inference instance.
    """
    try:
        model = (
            db.query(DBModel).filter(DBModel.id == instance.model.id).first()
        )
        engine = (
            db.query(DBEngine)
            .filter(DBEngine.id == instance.engine.id)
            .first()
        )

        if not model or not engine:
            logger.error(
                f"Model or Engine not found: model_id={instance.model.id}, engine_id={instance.engine.id}"
            )
            raise HTTPException(
                status_code=404, detail="Model or Engine not found"
            )

        reference = None
        if instance.serving_option_id is not None:
            serving_option = (
                db.query(ServingOption)
                .filter(
                    ServingOption.id == instance.serving_option_id,
                    ServingOption.model_id == model.id,
                )
                .first()
            )
            if not serving_option:
                logger.error(
                    f"Serving option not found for model {model.id}: "
                    f"{instance.serving_option_id}"
                )
                raise HTTPException(
                    status_code=404, detail="Serving option not found"
                )
            reference = serving_option.reference

        engine_chart = _engine_chart_query(db, engine.name, model.category)
        if not engine_chart:
            logger.error(
                f"Model Engine combination is invalid: model: {model.name}, engine: {engine.name}"
            )

        HF_API_TOKEN = os.environ.get("HF_API_TOKEN")
        NGC_API_KEY = os.environ.get("NGC_API_KEY")

        if engine.name == "nim" and not NGC_API_KEY:
            logger.error("NGC API key not set")
            raise HTTPException(status_code=400, detail="NGC API key not set")
        if engine.name.lower() not in NO_HF_TOKEN_ENGINES and not HF_API_TOKEN:
            logger.error("HuggingFace API token not set")
            raise HTTPException(
                status_code=400, detail="HuggingFace API token not set."
            )

        config_data = instance.config.model_dump() if instance.config else {}
        _record_window(config_data, engine, model)

        # Handle lora_adapters separately
        lora_adapters = update_config_with_lora_adapters(
            db, config_data.pop("lora_adapters", [])
        )
        db_config = DBInferenceInstanceConfigParams(**config_data)
        db_config.lora_adapters = lora_adapters

        db_instance = DBInferenceInstance(
            model_id=instance.model.id,
            engine_id=instance.engine.id,
            host=instance.host,
            endpoint=instance.endpoint or "",
            healthEndpoint=instance.healthEndpoint or "",
            metricsEndpoint=instance.metricsEndpoint or "",
            config=db_config,
            org_id=user.org_id,
            owner_id=user.id,
            reference=reference,
            status=STATUS_PENDING,
            replicas=instance.replicas,
            gpu_count=instance.gpu_count,
            cpu=instance.cpu,
            memory=instance.memory,
        )

        db.add(db_config)
        db.add(db_instance)
        db.commit()
        db.refresh(db_instance)

        full_instance = InferenceInstanceSchema.model_validate(db_instance)

        logger.debug(
            f"Full instance:\n{pprint.pformat(full_instance.model_dump(), indent=4, width=120)}"
        )

        try:
            controller = get_controller(engine.name)
            # Construction alone is cheap and never touches the cluster
            # (see the Controller docstring), so without this the branch
            # never fires: a missing kubeconfig would only surface later
            # as "Failed to install Helm chart: ...". ensure_ready()
            # forces the kube client, off the event loop, to make this a
            # real pre-flight again.
            await asyncio.to_thread(controller.ensure_ready)
        except Exception as e:
            logger.exception(f"Failed to build the controller: {str(e)}")
            mark_failed(db, db_instance, e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to build the controller: {str(e)}",
            )

        try:
            credential_value = generate_secret(seed=str(db_instance.id))
            await asyncio.to_thread(
                store_credential,
                db,
                controller.namespace,
                CREDENTIAL_KIND,
                db_instance.id,
                credential_value,
            )
        except Exception as e:
            logger.exception(f"Failed to store credential: {str(e)}")
            mark_failed(db, db_instance, e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to store credential: {str(e)}",
            )

        try:
            await controller.install(full_instance, engine_chart)
        except Exception as e:
            logger.exception(f"Failed to install Helm chart: {str(e)}")
            mark_failed(db, db_instance, e)
            await _uninstall_best_effort(controller, full_instance)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to install Helm chart: {str(e)}",
            )

        await asyncio.to_thread(
            register_instance,
            db,
            db_instance,
            full_instance,
            engine_chart,
            controller,
            credential_value,
        )
        full_instance = InferenceInstanceSchema.model_validate(db_instance)

        await create_instance_dashboards(full_instance, engine_chart, db)

        return full_instance
    except HTTPException:
        logger.exception("HTTPException in create_inference_instance")
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Error in create_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


def update_config_with_lora_adapters(db, lora_adapters):
    """
    Update the configuration with LoRA adapters.

    Args:
        lora_adapters (list): A list of LoRA adapter configurations.

    Returns:
        list: A list of DBModelAdapters objects.

    Raises:
        HTTPException: If a model adapter is not found.
    """
    lora_adapters_list = []
    for adapter in lora_adapters:
        existing_adapter = (
            db.query(DBModelAdapters)
            .filter(DBModelAdapters.id == adapter["id"])
            .first()
        )
        if existing_adapter:
            lora_adapters_list.append(existing_adapter)
        else:
            logger.error(f"Model adapter with id {adapter['id']} not found")
            raise HTTPException(
                status_code=404, detail="Model adapter not found"
            )
    return lora_adapters_list


@router.put(
    "/v1alpha1/inferenceInstance/{id}", response_model=InferenceInstanceSchema
)
async def update_inference_instance(
    id: uuid.UUID,
    updated_instance: InferenceInstanceSchema,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Update an existing inference instance.

    Args:
        id (uuid.UUID): The ID of the inference instance to update.
        updated_instance (InferenceInstanceSchema): The updated inference instance data.

    Returns:
        InferenceInstanceSchema: The updated inference instance.

    Raises:
        HTTPException: If the inference instance is not found or there's an error during the update.
    """
    try:
        db_instance = (
            db.query(DBInferenceInstance)
            .filter(DBInferenceInstance.id == id)
            .first()
        )
        if not db_instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(
                status_code=404, detail="Inference instance not found"
            )
        authorize_write(user, db_instance, "inference instance")

        for key, value in updated_instance.model_dump(
            exclude_unset=True
        ).items():
            # model and engine are the instance's identity (release name,
            # chart); they are ORM relationships and never change through
            # PUT, so a plain setattr with the dumped dict would crash.
            if key in READ_ONLY_STATUS_FIELDS or key in ("model", "engine"):
                continue
            if key == "config":
                update_config_params(db, db_instance, value)
            else:
                setattr(db_instance, key, value)

        engine, engine_chart = _engine_chart_for(db, db_instance)

        full_instance = InferenceInstanceSchema.model_validate(db_instance)

        controller = get_controller(engine.name)

        try:
            await controller.upgrade(full_instance, engine_chart)
        except GatewayPolicyError as e:
            # Helm succeeded and the workload is running, but the gateway
            # deleted the inf- route (fail closed, #27), so the host now
            # 404s while the poller keeps refilling the endpoint. Record
            # it; a plain Helm failure below changes nothing, because
            # there the instance is still serving as it was.
            logger.exception(f"Failed to protect the route: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to protect the gateway route: {str(e)}",
            )
        except Exception as e:
            logger.exception(f"Failed to upgrade Helm chart: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upgrade Helm chart: {str(e)}",
            )

        db.commit()
        db.refresh(db_instance)
        return db_instance
    except HTTPException:
        logger.exception("HTTPException in update_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in update_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


def update_config_params(db, db_instance, value):
    """
    Update the configuration parameters of an inference instance.

    Args:
        db_instance (DBInferenceInstance): The inference instance to update.
        value (dict): The new configuration values.
    """
    for config_key, config_value in value.items():
        if config_key == "lora_adapters":
            update_lora_adapters_in_inference_instance_config(
                db, db_instance, config_key, config_value
            )
        else:
            setattr(db_instance.config, config_key, config_value)


def update_lora_adapters_in_inference_instance_config(
    db, db_instance, config_key, config_value
):
    """
    Update the LoRA adapters in the inference instance configuration.

    Args:
        db_instance (DBInferenceInstance): The inference instance to update.
        config_key (str): The configuration key for LoRA adapters.
        config_value (list): The new LoRA adapter configurations.

    Raises:
        HTTPException: If a model adapter is not found.
    """
    for adapter in config_value:
        existing_adapter = (
            db.query(DBModelAdapters)
            .filter(DBModelAdapters.id == adapter["id"])
            .first()
        )
        if existing_adapter:
            setattr(db_instance.config, config_key, config_value)
        else:
            logger.error(f"Model adapter with id {adapter['id']} not found")
            raise HTTPException(
                status_code=404, detail="Model adapter not found"
            )


@router.delete("/v1alpha1/inferenceInstance/{id}")
async def delete_inference_instance(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Delete an inference instance.

    Args:
        id (uuid.UUID): The ID of the inference instance to delete.

    Returns:
        dict: A message confirming the deletion.

    Raises:
        HTTPException: If the inference instance is not found or there's an error during deletion.
    """
    try:
        db_instance = (
            db.query(DBInferenceInstance)
            .filter(DBInferenceInstance.id == id)
            .first()
        )
        if not db_instance:
            logger.error(f"Inference instance not found: {id}")
            raise HTTPException(
                status_code=404, detail="Inference instance not found"
            )
        authorize_write(user, db_instance, "inference instance")

        full_instance = InferenceInstanceSchema.model_validate(db_instance)
        # A Failed launch may have no release and no reachable cluster
        # behind it (the install failed before or while talking to
        # Kubernetes); its row must still be deletable, so for a Failed
        # row a controller or uninstall failure is logged, not fatal.
        failed = db_instance.status == STATUS_FAILED
        controller = None
        try:
            controller = get_controller(full_instance.engine.name)
        except Exception as e:
            if not failed:
                raise
            logger.warning(
                f"Deleting failed instance {id} without a controller: {e}"
            )

        await asyncio.to_thread(unregister_instance, db_instance)

        if controller is not None:
            try:
                await controller.uninstall(full_instance)
            except Exception as e:
                if not failed:
                    logger.exception(f"Failed to remove Helm chart: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to remove Helm chart: {str(e)}",
                    )
                logger.warning(
                    f"Deleting failed instance {id}; uninstall failed: {e}"
                )

        # Also without a controller: the Secrets were written before the
        # install, so inf-<id8>-credentials/-apikey-auth must not stay
        # behind a Failed row. The namespace comes from the controller,
        # else from the credential row, else the default.
        try:
            await asyncio.to_thread(
                delete_credential,
                db,
                _credential_namespace(db, controller, id),
                CREDENTIAL_KIND,
                id,
            )
        except Exception as e:
            # A stray Secret must not block deleting the row: the Helm
            # release is already gone. The bookkeeping row goes with the
            # instance row (nobody retries a deleted instance; the
            # Secrets carry MANAGED_BY_LABEL for an operator sweep).
            logger.exception(f"Error deleting credential: {e}")
            _forget_credential(db, CREDENTIAL_KIND, id)

        try:
            instance_dashboards = (
                db.query(DBInferenceInstanceDashboards)
                .filter(
                    DBInferenceInstanceDashboards.inference_instance_id == id
                )
                .all()
            )
            if instance_dashboards:
                for dashboard in instance_dashboards:
                    db.delete(dashboard)
        except Exception as e:
            logger.exception(f"Error deleting dashboards: {e}")

        # Never inside the dashboards try: a swallowed error here would
        # answer 200 with the row still present.
        if db_instance.config is not None:
            db.delete(db_instance.config)
        db.delete(db_instance)
        db.commit()

        return {"detail": "Inference instance deleted"}
    except HTTPException:
        logger.exception("HTTPException in delete_inference_instance")
        raise
    except Exception as e:
        logger.exception(f"Error in delete_inference_instance: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _forget_credential(db: Session, kind: str, id: uuid.UUID) -> None:
    """Drop the credential bookkeeping row when its Secrets could not be
    deleted but the instance row is going anyway."""
    credential = find_credential(db, kind, id)
    if credential is not None:
        db.delete(credential)


def _credential_namespace(db: Session, controller, id: uuid.UUID) -> str:
    """Where the instance's credential Secrets live."""
    if controller is not None:
        return controller.namespace
    credential = find_credential(db, CREDENTIAL_KIND, id)
    if credential is not None:
        return credential.namespace
    return get_default_namespace()


async def create_instance_dashboards(
    instance: InferenceInstanceSchema,
    engine_chart: DBEngineCharts,
    db: Session,
):
    """
    Create dashboards for an inference instance.

    Args:
        instance (InferenceInstanceSchema): The inference instance to create dashboards for.
        engine_chart (DBEngineCharts): The engine chart to create dashboards for.
        db (Session): The database session.

    Raises:
        HTTPException: If no dashboards are found for the engine chart.
    """
    try:
        engine_chart_dashboards = (
            db.query(DBEngineChartDashboards)
            .filter(
                and_(
                    DBEngineChartDashboards.engine_id == instance.engine.id,
                    DBEngineChartDashboards.engine_chart_id == engine_chart.id,
                )
            )
            .all()
        )
        if not engine_chart_dashboards:
            logger.error(
                f"No dashboards found for engine chart: {engine_chart.id}"
            )
            return

        for chart_dashboard in engine_chart_dashboards:
            controller = get_controller(instance.engine.name)
            namespace = controller.namespace
            service_name = controller.get_service_name(instance, engine_chart)
            query_params = {
                "var-namespace": namespace,
                "var-service": service_name,
                # The LiteLLM dashboard filters on the target name.
                "var-target": instance_model_name(instance.id),
            }
            inference_instance_dashboard = DBInferenceInstanceDashboards(
                id=genid.uuid4(),
                inference_instance_id=instance.id,
                engine_chart_dashboard_id=chart_dashboard.id,
                org_id=GRAFANA_ORG_ID,
                query_params=json.dumps(query_params),
            )
            db.add(inference_instance_dashboard)

        db.commit()
    except Exception as e:
        logger.exception(f"Error creating instance dashboards: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error creating instance dashboards: {e}"
        )
