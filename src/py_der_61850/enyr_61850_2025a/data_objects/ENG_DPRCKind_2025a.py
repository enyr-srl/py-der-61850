from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.DPRCKind_2025a import DPRCKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType


class ENG_DPRCKind_2025a(DOType):
    """Abstract type, holding attributes common to integer status settings with the value restricted to those in an enumeration."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for configuration, description and extension
        self.setVal: DPRCKind_2025a = DPRCKind_2025a(98)  # The value of the status setting.
