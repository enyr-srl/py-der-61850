from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a


class ORG_Frcs_LOD_2025a:
    """This common data class shall be used to represent object reference settings."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for setting
        self.setSrcRef: FFRC_LOD_2025a  # The value of the object reference setting as specified in the context where the common data class is used.
