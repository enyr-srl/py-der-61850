from pydantic import PrivateAttr

from py_der_61850.clients.huawei_device_client import HuaweiDeviceClient
from py_der_61850.clients.huawei_idle_device_client import HuaweiIdleDeviceClient

from .protocol_client_registry import ProtocolClientRegistry
from .source_protocol_config import SourceProtocolConfig
from .source_protocol_registry import register_source_protocol


@register_source_protocol("huawei")
class HuaweiSourceProtocolConfig(SourceProtocolConfig):
    address: str
    function: str
    unit: str
    devId: int
    multiplier: float
    _client: HuaweiDeviceClient = PrivateAttr(default=HuaweiIdleDeviceClient())

    def read(self) -> None:
        result = self._client.read(
            address=self.address,
            type=self.ref_value.type,
            function=self.function,
            devId=self.devId,
            multiplier=self.multiplier,
        )
        self.ref_value.raw_value = result

    def read_blocks(self, blocks: list[dict[str, int]], addresses: list[int]) -> dict[int, int]:
        return {}

    def set_protocol_client(self, registry: ProtocolClientRegistry) -> None:
        self._client = registry.get("huawei")
