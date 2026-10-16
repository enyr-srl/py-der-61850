class ModbusDeviceClient:

    def read(
        self, address: int, type: str, function: str, multiplier: int, signed: int | None, bit_index: int | None
    ) -> str:
        """Read device data."""
        raise NotImplementedError("This method should be overridden by subclasses")

    def read_blocks(self, blocks: list[dict[str, int]], addresses: list[int]) -> dict[int, int]:
        """Read a block of device data."""
        raise NotImplementedError("This method should be overridden by subclasses")

    def write(
        self, value: str, address: int, type: str, function: str, multiplier: int, bit_index: int | None
    ) -> None:
        """Write device data."""
        raise NotImplementedError("This method should be overridden by subclasses")
