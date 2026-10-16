from pydantic import PrivateAttr

from py_der_61850.clients.modbus_client import ModbusDeviceClient
from py_der_61850.clients.modbus_idle_device_client import ModbusIdleDeviceClient

from .protocol_client_registry import ProtocolClientRegistry
from .source_protocol_config import SourceProtocolConfig
from .source_protocol_registry import register_source_protocol


@register_source_protocol("modbus")
class ModbusSourceProtocolConfig(SourceProtocolConfig):
    slaived: int
    address: int
    function: str
    multiplier: int
    signed: int | None = None
    unit: str
    bit_index: int | None = None
    _client: ModbusDeviceClient = PrivateAttr(default=ModbusIdleDeviceClient())

    def read(self) -> None:
        result = self._client.read(
            address=self.address,
            type=self.ref_value.type,
            function=self.function,
            multiplier=self.multiplier,
            signed=self.signed,
            bit_index=self.bit_index,
        )
        self.ref_value.raw_value = result

    def read_blocks(self, blocks: list[dict[str, int]], addresses: list[int]) -> dict[int, int]:
        return self._client.read_blocks(blocks, addresses)

    def set_protocol_client(self, registry: ProtocolClientRegistry) -> None:
        self._client = registry.get("modbus")
