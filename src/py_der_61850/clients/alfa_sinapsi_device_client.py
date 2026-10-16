class AlfaSinapsiDeviceClient:

    def read(self, pod: str, obis: str, unit: str, activation_key: str, multiplier: float) -> str:
        """Read device data."""
        raise NotImplementedError("This method should be overridden by subclasses")

    def write(self, value: str, control_type: int) -> None:
        """Write device data."""
        raise NotImplementedError("This method should be overridden by subclasses")
