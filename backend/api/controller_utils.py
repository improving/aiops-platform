from controller import HuggingFaceController, NIMController, VLLMController

async def get_controller(engine_name: str):
    if engine_name.lower() == "HuggingFace":
        return HuggingFaceController()
    elif engine_name.lower() == "nim":
        return NIMController()
    elif engine_name.lower() == "vllm":
        return VLLMController()
    else:
        raise ValueError(f"Unsupported engine: {engine_name}")