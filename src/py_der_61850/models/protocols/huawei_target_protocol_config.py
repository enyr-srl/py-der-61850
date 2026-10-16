from typing import Any

from pydantic import PrivateAttr

from py_der_61850.clients.huawei_device_client import HuaweiDeviceClient
from py_der_61850.clients.huawei_idle_device_client import HuaweiIdleDeviceClient
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.models.protocols.protocol_client_registry import ProtocolClientRegistry

from .target_protocol_config import TargetProtocolConfig
from .target_protocol_registry import register_target_protocol


@register_target_protocol("huawei")
class HuaweiTargetProtocolConfig(TargetProtocolConfig):
    control_type: int
    _client: HuaweiDeviceClient = PrivateAttr(default=HuaweiIdleDeviceClient())

    def write(self, do_type: DOType) -> Any:

        q: Quality_2025a | None = getattr(do_type, "q", None)
        if self.ref_value.raw_value is None:
            raise ValueError("Cannot write None value to Huawei target")

        if q and q.validity == ValidityKind_2025a.good:
            return self._client.write(
                value=self.ref_value.raw_value,
                control_type=self.control_type,
                command_timestamp=getattr(do_type, "t", None),
            )
        return None

    def set_protocol_client(self, registry: ProtocolClientRegistry) -> None:
        self._client = registry.get("huawei")
