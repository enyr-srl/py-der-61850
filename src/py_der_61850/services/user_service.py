from typing import Dict, List

from py_der_61850.models.protocols.protocol_client_registry import ProtocolClientRegistry
from py_der_61850.models.protocols.value import Value
from py_der_61850.models.user_schema import Assignment, AssignmentValue, DataAttribute, LNDeclaration, User


class UserService:
    def __init__(
        self,
        user: User,
        protocol_client_registry: ProtocolClientRegistry | None = None,
    ):
        self.user = user
        if protocol_client_registry:
            self.set_protocol_clients(protocol_client_registry)

    def search_attribute(self, attribute: str) -> Value | None:
        for device in self.user.devices:
            for ln in device.lns:
                for do in ln.dos:
                    for da in do.das:
                        if attribute.lower() == da.id.lower():
                            return da.value
        return None

    def get_data_attributes(self) -> dict[str, DataAttribute]:
        user_id = self.user.id
        image_process: dict[str, DataAttribute] = {}
        for device in self.user.devices:
            device_id = device.id
            for ln in device.lns:
                ln_id = ln.id
                ln_instance = f"{user_id}_{device_id}_{ln_id}"
                for do in ln.dos:
                    do_id = do.id
                    for da in do.das:
                        da_id = da.id
                        id = f"{ln_instance}.{do_id}.{da_id}"
                        image_process[id] = da
        return image_process

    def set_protocol_clients(self, protocol_client_registry: ProtocolClientRegistry):
        for device in self.user.devices:
            for ln in device.lns:
                for do in ln.dos:
                    for da in do.das:
                        if da.mapping.target.protocol != "default":
                            da.mapping.target.config.set_protocol_client(protocol_client_registry)
                        if da.mapping.source.protocol != "default":
                            da.mapping.source.config.set_protocol_client(protocol_client_registry)

    def ln_declarations(self) -> List[LNDeclaration]:
        ln_declarations: List[LNDeclaration] = []
        user_id = self.user.id
        for device in self.user.devices:
            device_id = device.id
            for ln in device.lns:
                ln_id = ln.id
                ln_instance = f"{user_id}_{device_id}_{ln_id}"
                ln_type = ln.type
                ln_declarations.append(LNDeclaration(instance=ln_instance, type=ln_type))
        return ln_declarations

    def assignments(self) -> Dict[str, Assignment]:
        assignments: Dict[str, Assignment] = {}
        user_id = self.user.id
        for device in self.user.devices:
            device_id = device.id
            for ln in device.lns:
                ln_id = ln.id
                ln_instance = f"{user_id}_{device_id}_{ln_id}"
                for do in ln.dos:
                    do_id = do.id
                    for da in do.das:
                        da_id = da.id
                        da_value = da.value
                        full_id = f"{ln_instance}.{do_id}.{da_id}"
                        da_raw_value = da_value.raw_value
                        if da_raw_value:
                            assignments.update(
                                {
                                    full_id: Assignment(
                                        object=f"{ln_instance}.{do_id}",
                                        property=f"{da_id}",
                                        value=AssignmentValue(type=da_value.type, raw_value=da_raw_value),
                                    )
                                }
                            )
        return assignments
