from abc import abstractmethod

from .protocol_config import ProtocolConfig


class SourceProtocolConfig(ProtocolConfig):
    @abstractmethod
    def read(self):
        pass

    @abstractmethod
    def read_blocks(self, blocks: list[dict[str, int]], addresses: list[int]) -> dict[int, int]:
        pass
