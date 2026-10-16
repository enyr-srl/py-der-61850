from pydantic import PrivateAttr

from py_der_61850.clients.alfa_sinapsi_device_client import AlfaSinapsiDeviceClient
from py_der_61850.clients.alfa_sinapsi_idle_device_client import AlfaSinapsiIdleDeviceClient

from .protocol_client_registry import ProtocolClientRegistry
from .source_protocol_config import SourceProtocolConfig
from .source_protocol_registry import register_source_protocol


@register_source_protocol("alfa")
class AlfaSinapsiSourceProtocolConfig(SourceProtocolConfig):
    pod: str
    obis: str
    unit: str
    activation_key: str
    multiplier: float
    _client: AlfaSinapsiDeviceClient = PrivateAttr(default=AlfaSinapsiIdleDeviceClient())

    def read(self) -> None:
        result = self._client.read(
            pod=self.pod,
            obis=self.obis,
            unit=self.unit,
            activation_key=self.activation_key,
            multiplier=self.multiplier,
        )
        self.ref_value.raw_value = result

    def read_blocks(self, blocks: list[dict[str, int]], addresses: list[int]) -> dict[int, int]:
        return {}

    def set_protocol_client(self, registry: ProtocolClientRegistry) -> None:
        self._client = registry.get("alfa")
