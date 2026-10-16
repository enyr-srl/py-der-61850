from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.DCSCKind_2025a import DCSCKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType


class ENG_DCSCKind_2025a(DOType):
    """Abstract type, holding attributes common to integer status settings with the value restricted to those in an enumeration."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for configuration, description and extension
        self.setVal: DCSCKind_2025a = DCSCKind_2025a(98)  # The value of the status setting.
