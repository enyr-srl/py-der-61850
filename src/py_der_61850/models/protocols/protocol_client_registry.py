from typing import Any


class ProtocolClientRegistry:
    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def register(self, protocol: str, client: Any) -> None:
        self._clients[protocol] = client

    def get(self, protocol: str) -> Any:
        client = self._clients.get(protocol)
        if client is None:
            raise ValueError(f"No client registered for protocol '{protocol}'")
        return client
