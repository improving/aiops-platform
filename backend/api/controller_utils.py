from controller import HuggingFaceController, NIMController, VLLMController
from controller.vectordb_controller import VectorDBController

async def get_controller(engine_name: str):
    if engine_name.lower() == "huggingface":
        return HuggingFaceController()
    elif engine_name.lower() == "nim":
        return NIMController()
    elif engine_name.lower() == "vllm":
        return VLLMController()
    elif (engine_name.lower() == "chromadb" or 
          engine_name.lower() == "milvus" or 
          engine_name.lower() == "qdrant"):
        return VectorDBController()
    else:
        raise ValueError(f"Unsupported engine: {engine_name}")