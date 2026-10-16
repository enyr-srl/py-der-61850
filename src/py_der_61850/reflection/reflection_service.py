from dataclasses import dataclass
from typing import Any

from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType

from .reflection_strategy import ReflectionStrategy


@dataclass
class ReflectValue:
    object: str
    property: str
    value: str
    type: str


class ReflectionService:
    def __init__(self, reflection_strategy: ReflectionStrategy):
        self.__reflection_strategy: ReflectionStrategy = reflection_strategy
        self.__initialize()

    def set_values(self, reflect_values: list[ReflectValue]):
        for reflect_value in reflect_values:
            self.__reflection_strategy.set_value(
                reflect_value.object, reflect_value.property, reflect_value.value, reflect_value.type
            )

    def get_value(self, id: str) -> Any | None:
        return self.__reflection_strategy.get_value(id)

    def get_do(self, id: str) -> DOType:
        do = self.__reflection_strategy.get_value(id)
        if isinstance(do, DOType):
            return do
        raise ValueError(f"ID {id} is not a DOType")

    def call(self) -> None:
        self.__reflection_strategy.call()

    def __initialize(self) -> None:
        self.__reflection_strategy.instantiate()
