from dataclasses import dataclass


@dataclass
class Value:
    type: str
    raw_value: str | None
