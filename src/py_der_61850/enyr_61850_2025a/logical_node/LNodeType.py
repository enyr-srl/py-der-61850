from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.models.config_visitor import ConfigVisitor


class LNodeType:
    def __init__(self, visitor: ConfigVisitor) -> None:
        self._visitor = visitor

    def __call__(
        self,
    ) -> None:
        pass

    def get(self, id: str) -> DOType | None:
        return getattr(self, id, None)

    def get_all(self) -> dict[str, DOType]:
        return self.__dict__.copy()
