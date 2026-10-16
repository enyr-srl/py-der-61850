from typing import TYPE_CHECKING

from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType

if TYPE_CHECKING:
    from py_der_61850.enyr_61850_2025a.logical_node.DSTO_2025a import DSTO_2025a


class ORG_DSTO_2025a(DOType):
    """This common data class shall be used to represent object reference settings."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for setting
        self.setSrcRef: DSTO_2025a  # The value of the object reference setting as specified in the context where the common data class is used.
