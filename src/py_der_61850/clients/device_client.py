from abc import ABC, abstractmethod
from typing import Any


class DeviceClient(ABC):

    @abstractmethod
    def read(self) -> Any:
        """Read device data."""
        pass

    @abstractmethod
    def write(self) -> Any:
        """Write device data."""
        pass
