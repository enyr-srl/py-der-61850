from pydantic import BaseModel


class MQTTMessage(BaseModel):
    id: str
    type: str
    value: str
    quality: str | None = None
    do_timestamp: str | None = None
    timestamp: str
    store: bool = False


class MQTTPayload(BaseModel):
    messages: list[MQTTMessage]
