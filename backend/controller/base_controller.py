from abc import ABC, abstractmethod
from schemas.inference_instance import InferenceInstanceSchema

class Controller(ABC):
    @abstractmethod
    async def install(self, instance: InferenceInstanceSchema):
        pass

    @abstractmethod
    async def upgrade(self, instance: InferenceInstanceSchema):
        pass

    @abstractmethod
    async def remove(self, instance: InferenceInstanceSchema):
        pass