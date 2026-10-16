from typing import Dict, Type

from .source_protocol_config import SourceProtocolConfig

source_protocol_registry: Dict[str, Type[SourceProtocolConfig]] = {}


def register_source_protocol(name: str):
    def wrapper(cls: Type[SourceProtocolConfig]):
        source_protocol_registry[name] = cls
        return cls

    return wrapper


def get_source_protocol_config(values: dict) -> dict:
    protocol = values.get("protocol")
    if protocol == "default":
        return values
    raw_config = values.get("config")

    if not protocol:
        raise ValueError("'protocol' is required.")

    if not raw_config:
        raise ValueError("'config' is required.")

    config_cls: type[SourceProtocolConfig] | None = source_protocol_registry.get(protocol)
    if not config_cls:
        raise ValueError(f"Unsupported protocol: {protocol}")
    values["config"] = config_cls(**raw_config)
    return values
