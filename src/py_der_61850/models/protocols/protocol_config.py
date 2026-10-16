from abc import ABC

from pydantic import BaseModel, Field

from .protocol_client_registry import ProtocolClientRegistry
from .value import Value


class ProtocolConfig(BaseModel, ABC):
    ref_value: Value = Field(default_factory=lambda: Value("unset", None))

    def set_protocol_client(self, registry: ProtocolClientRegistry) -> None:
        pass
