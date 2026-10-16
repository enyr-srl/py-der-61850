from typing import Dict, Type

from .target_protocol_config import TargetProtocolConfig

target_protocol_registry: Dict[str, Type[TargetProtocolConfig]] = {}


def register_target_protocol(name: str):
    def wrapper(cls: Type[TargetProtocolConfig]):
        target_protocol_registry[name] = cls
        return cls

    return wrapper


def get_target_protocol_config(values: dict) -> dict:
    protocol = values.get("protocol")
    if protocol == "default":
        return values
    raw_config = values.get("config")

    if not protocol:
        raise ValueError("'protocol' is required.")

    if not raw_config:
        raise ValueError("'config' is required.")

    config_cls: type[TargetProtocolConfig] | None = target_protocol_registry.get(protocol)
    if not config_cls:
        raise ValueError(f"Unsupported protocol: {protocol}")
    values["config"] = config_cls(**raw_config)
    return values
