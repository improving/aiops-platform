from .hf_controller import HuggingFaceController
from .nim_controller import NIMController
from .notebooks_controller import NotebooksController
from .ollama_controller import OllamaController
from .opea_controller import OPEAController
from .vectordb_controller import VectorDBController
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
    if engine_name.lower() == "ollama":
        return OllamaController(*args, **kwargs)
    raise ValueError(f"Unsupported engine: {engine_name}")
