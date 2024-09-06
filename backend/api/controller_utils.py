from controller import TGIController, NIMController, VLLMController

async def get_controller(engine_name: str):
    if engine_name.lower() == "tgi":
        return TGIController()
    elif engine_name.lower() == "nim":
        return NIMController()
    elif engine_name.lower() == "vllm":
        return VLLMController()
    else:
        raise ValueError(f"Unsupported engine: {engine_name}")