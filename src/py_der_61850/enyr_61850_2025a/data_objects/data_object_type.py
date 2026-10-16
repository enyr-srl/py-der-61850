from enum import Enum


class DOType:
    def get(self, id: str) -> Enum | int | float | bool | None:
        return getattr(self, id, None)

    def get_all(self) -> dict[str, Enum | int | float | bool]:
        return self.__dict__.copy()
