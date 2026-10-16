from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType


class ORS_2025a(DOType):
    """This common data class shall be used to hold the reference to an element the data is referring to."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for setting
        self.stVal: str = ""  # Reference to an element the data is referring to.
