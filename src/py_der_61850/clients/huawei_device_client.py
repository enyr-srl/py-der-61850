from datetime import datetime


class HuaweiDeviceClient:

    def read(self, address: str, type: str, function: str, devId: int, multiplier: float) -> str:
        """Read device data."""
        raise NotImplementedError("This method should be overridden by subclasses")

    def write(self, value: str, control_type: int, command_timestamp: datetime | None = None) -> str | None:
        """Write device data."""
        raise NotImplementedError("This method should be overridden by subclasses")
