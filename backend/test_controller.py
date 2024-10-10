import uuid
from unittest import mock

import pytest
import yaml
from fastapi.testclient import TestClient

from app import app
from controller import get_controller
from schemas import (EngineChartsSchema, EngineSchema,
                     InferenceInstanceConfigParamsSchema,
                     InferenceInstanceSchema, ModelSchema)


def test_controller():
    for engine_name in ["huggingface", "nim", "vllm", "opea"]:
        controller = get_controller(engine_name, core_v1_api=mock.Mock())
        assert controller is not None


@pytest.mark.asyncio
async def test_controller_helm_values(snapshot):  # pylint: disable=R0914
    client = TestClient(app)
    engines = client.get("/v1alpha1/engines").json()
    models = client.get("/v1alpha1/models").json()

    # load list of models in modelschema
    model_schemas = [ModelSchema(**model) for model in models]

    # load list of engines in engine schema
    engine_schemas_map = {
        engine["name"].lower(): EngineSchema(**engine)
        for engine in engines
    }

    # get model schema for model id
    model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    model_schema = next(
        (model for model in model_schemas if model.modelId == model_id), None)
    if model_schema is None:
        raise ValueError(f"Model with id {model_id} not found")

    # build map of engine schemas
    engineChartMaps = {
        "huggingface": {
            "chart_repo": "https://infracloudio.github.io/charts",
            "chart_name": "text-generation-inference",
            "chart_type": "llm",
        },
        "vllm": {
            "chart_repo": "https://infracloudio.github.io/charts",
            "chart_name": "vllm",
            "chart_type": "llm",
        },
        "nim": {
            "chart_repo": "https://helm.ngc.nvidia.com/nim/charts/",
            "chart_name": "nim-llm-1.1.2.tgz",
            "chart_type": "llm",
        },
    }
    for engine_name, engine_schema in engine_schemas_map.items():
        if engine_name == "opea":
            continue
        controller = get_controller(engine_name, core_v1_api=mock.Mock())
        assert controller is not None
        instance = InferenceInstanceSchema(
            id=uuid.uuid4(),
            model=model_schema,
            engine=engine_schema,
            host="gpu-node-3",
            config=InferenceInstanceConfigParamsSchema(
                id=uuid.uuid4(),
                maxInputLength=100,
                maxTokens=100,
                maxBatchPrefillTokens=100,
                maxBatchTotalTokens=100,
                quantization="test",
                image="test",
                lora_adapters=[],
            ),
        )
        engine_chart_map = engineChartMaps[engine_name]
        engine_chart = EngineChartsSchema(
            id=uuid.uuid4(),
            engine=engine_name,
            chart_type=engine_chart_map["chart_type"],
            chart_repo=engine_chart_map["chart_repo"],
            chart_name=engine_chart_map["chart_name"],
        )
        values = await controller.prepare_helm_values(instance, engine_chart)
        values_yaml = yaml.dump(values)
        snapshot.assert_match(values_yaml,
                              engine_name.lower() + "-values.yaml")
