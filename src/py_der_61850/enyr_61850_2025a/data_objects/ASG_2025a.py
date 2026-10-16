from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType


class ASG_2025a(DOType):
    """Abstract type, holding attributes common to analogue settings."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for setting
        self.setMag: float = 0.0  # 	The value of the analogue setting.
