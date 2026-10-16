from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.SIUnitKind_2025a import SIUnitKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType


class Unit_SIUnitKind_2025a(DOType):
    """This type shall be used to represent unit and multiplier information."""

    def __init__(
        self,
    ) -> None:
        self.SIUnit: SIUnitKind_2025a = SIUnitKind_2025a(1)  # SI unit of measure
