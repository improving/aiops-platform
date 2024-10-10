from .base_controller import Controller
from .hf_controller import HuggingFaceController
from .nim_controller import NIMController
from .opea_controller import OPEAController
from .vllm_controller import VLLMController


def get_controller(engine_name: str, *args, **kwargs):
    if engine_name.lower() == "huggingface":
        return HuggingFaceController(*args, **kwargs)
    if engine_name.lower() == "nim":
        return NIMController(*args, **kwargs)
    if engine_name.lower() == "vllm":
        return VLLMController(*args, **kwargs)
    if engine_name.lower() == "opea":
        return OPEAController(*args, **kwargs)
    raise ValueError(f"Unsupported engine: {engine_name}")


__all__ = [
    "Controller",
    "HuggingFaceController",
    "NIMController",
    "VLLMController",
    "OPEAController",
    "get_controller",
]
