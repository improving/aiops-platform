from controller import HuggingFaceController, NIMController, VLLMController
from controller.opea_controller import OPEAController
from controller.vectordb_controller import VectorDBController


def get_controller(engine_name: str):
    if engine_name.lower() == "huggingface":
        return HuggingFaceController()
    if engine_name.lower() == "nim":
        return NIMController()
    if engine_name.lower() == "vllm":
        return VLLMController()
    if engine_name.lower() == "opea":
        return OPEAController()

    raise ValueError(f"Unsupported engine: {engine_name}")
