from pydantic import PrivateAttr

from py_der_61850.clients.alfa_sinapsi_device_client import AlfaSinapsiDeviceClient
from py_der_61850.clients.alfa_sinapsi_idle_device_client import AlfaSinapsiIdleDeviceClient
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.models.protocols.protocol_client_registry import ProtocolClientRegistry

from .target_protocol_config import TargetProtocolConfig
from .target_protocol_registry import register_target_protocol


@register_target_protocol("alfa")
class HuaweiTargetProtocolConfig(TargetProtocolConfig):
    control_type: int
    _client: AlfaSinapsiDeviceClient = PrivateAttr(default=AlfaSinapsiIdleDeviceClient())

    def write(self, do_type: DOType) -> None:

        q: Quality_2025a | None = getattr(do_type, "q", None)
        if self.ref_value.raw_value is None:
            raise ValueError("Cannot write None value to Modbus target")

        if q and q.validity == ValidityKind_2025a.good:
            self._client.write(
                value=self.ref_value.raw_value,
                control_type=self.control_type,
            )

    def set_protocol_client(self, registry: ProtocolClientRegistry) -> None:
        self._client = registry.get("alfa")
