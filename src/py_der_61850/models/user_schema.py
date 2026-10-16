from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

from .protocols.alfa_sinapsi_source_protocol_config import AlfaSinapsiDeviceClient as AlfaSinapsiDeviceClient
from .protocols.alfa_sinapsi_target_protocol_config import AlfaSinapsiIdleDeviceClient as AlfaSinapsiIdleDeviceClient
from .protocols.default_source_protocol_config import DefaultSourceProtocolConfig
from .protocols.default_target_protocol_config import DefaultTargetProtocolConfig
from .protocols.huawei_source_protocol_config import HuaweiSourceProtocolConfig as HuaweiSourceProtocolConfig
from .protocols.huawei_target_protocol_config import HuaweiTargetProtocolConfig as HuaweiTargetProtocolConfig
from .protocols.modbus_source_protocol_config import ModbusSourceProtocolConfig as ModbusSourceProtocolConfig
from .protocols.modbus_target_protocol_config import ModbusTargetProtocolConfig as ModbusTargetProtocolConfig
from .protocols.source_protocol_config import SourceProtocolConfig
from .protocols.source_protocol_registry import get_source_protocol_config
from .protocols.target_protocol_config import TargetProtocolConfig
from .protocols.target_protocol_registry import get_target_protocol_config
from .protocols.value import Value


@dataclass
class LNDeclaration:
    instance: str
    type: str


@dataclass
class AssignmentValue:
    type: str
    raw_value: str


@dataclass
class Assignment:
    object: str
    property: str
    value: AssignmentValue


class SourceMappingConfig(BaseModel):
    protocol: str = Field(..., description="The protocol used for the mapping")
    config: SourceProtocolConfig

    @model_validator(mode="before")
    @classmethod
    def resolve_config(cls, values: dict):
        return get_source_protocol_config(values)

    def set_reference_value(self, value: Value):
        self.config.ref_value = value


class TargetMappingConfig(BaseModel):
    protocol: str = Field(..., description="The protocol used for the mapping")
    config: TargetProtocolConfig

    @model_validator(mode="before")
    @classmethod
    def resolve_config(cls, values: dict):
        return get_target_protocol_config(values)

    def set_reference_value(self, value: Value):
        self.config.ref_value = value


class Mapping(BaseModel):
    source: SourceMappingConfig = Field(
        default_factory=lambda: SourceMappingConfig(protocol="default", config=DefaultSourceProtocolConfig())
    )
    target: TargetMappingConfig = Field(
        default_factory=lambda: TargetMappingConfig(protocol="default", config=DefaultTargetProtocolConfig())
    )

    def set_value_ref(self, value: Value):
        self.source.config.ref_value = value
        self.target.config.ref_value = value


class DataAttribute(BaseModel):
    id: str = Field(..., description="The unique identifier for the DAS")
    value: Value = Field(..., description="The value of the DAS")
    store: bool = Field(False, description="Whether to store the value of the DAS")
    bootstrap: str | None = Field(
        None,
        description="Optional runtime bootstrap policy for restoring the DA at startup.",
    )
    sendSet: bool | None = Field(
        None,
        description="Marks a DA as a cloud-to-edge command channel when present in configuration.",
    )
    mapping: Mapping = Field(
        default_factory=lambda: Mapping(
            source=SourceMappingConfig(protocol="default", config=DefaultSourceProtocolConfig()),
            target=TargetMappingConfig(protocol="default", config=DefaultTargetProtocolConfig()),
        ),
        description="Optional mapping configuration for the DAS",
    )

    @model_validator(mode="before")
    @classmethod
    def create_value(cls, values: dict):
        values["value"] = Value(type=values.get("type", "unset"), raw_value=values.get("value", None))
        return values

    def model_post_init(self, __context):
        self.mapping.set_value_ref(self.value)


class DataObject(BaseModel):
    id: str = Field(..., description="The unique identifier for the DOS")
    type: str = Field(..., description="The type of the DOS")
    das: list[DataAttribute]


class LogicalNode(BaseModel):
    id: str = Field(..., description="The unique identifier for the LN")
    type: str = Field(..., description="The type of the LN")
    dos: list[DataObject]


class Device(BaseModel):
    id: str = Field(..., description="The unique identifier for the device")
    lns: list[LogicalNode]


@dataclass
class DeviceRead:
    object: str
    property: str
    value: str
    type: str


@dataclass
class DeviceWrite:
    id: str
    da: DataAttribute


class User(BaseModel):
    id: str = Field(..., description="The unique identifier for the user")
    plant_code: str | None = Field(None, description="The plant code associated with the user")
    devices: list[Device]

    def get_protocols(self) -> list[str]:
        protocols = set()
        for device in self.devices:
            for ln in device.lns:
                for do in ln.dos:
                    for da in do.das:
                        if hasattr(da, "mapping"):
                            if hasattr(da.mapping.source, "protocol"):
                                if da.mapping.source.protocol != "default":
                                    protocols.add(da.mapping.source.protocol)
        return list(protocols)


class Users(BaseModel):
    users: list[User]
