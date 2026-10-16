from typing import Any

from .source_protocol_config import SourceProtocolConfig


class DefaultSourceProtocolConfig(SourceProtocolConfig):
    def read(self) -> Any:
        pass

    def read_blocks(self, blocks: list[dict[str, int]], addresses: list[int]) -> Any:
        pass
