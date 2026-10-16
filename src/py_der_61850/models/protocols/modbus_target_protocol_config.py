from pydantic import PrivateAttr

from py_der_61850.clients.modbus_client import ModbusDeviceClient
from py_der_61850.clients.modbus_idle_device_client import ModbusIdleDeviceClient
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType

from .protocol_client_registry import ProtocolClientRegistry
from .target_protocol_config import TargetProtocolConfig
from .target_protocol_registry import register_target_protocol


@register_target_protocol("modbus")
class ModbusTargetProtocolConfig(TargetProtocolConfig):
    slaived: int
    address: int
    function: str
    multiplier: int
    signed: int | None = None
    unit: str
    bit_index: int | None = None
    _client: ModbusDeviceClient = PrivateAttr(default=ModbusIdleDeviceClient())

    def write(self, do_type: DOType) -> None:
        dchg = getattr(do_type, "dchg", False)
        if self.ref_value.raw_value is None:
            raise ValueError("Cannot write None value to Modbus target")

        if dchg:
            self._client.write(
                value=self.ref_value.raw_value,
                address=self.address,
                type=self.ref_value.type,
                function=self.function,
                multiplier=self.multiplier,
                bit_index=self.bit_index,
            )
            setattr(do_type, "dchg", False)

    def set_protocol_client(self, registry: ProtocolClientRegistry) -> None:
        self._client = registry.get("modbus")
