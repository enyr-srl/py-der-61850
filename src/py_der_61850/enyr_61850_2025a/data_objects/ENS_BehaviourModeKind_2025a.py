from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.BehaviourModeKind_2025a import BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a


class ENS_BehaviourModeKind_2025a(DOType):
    """This common data class shall be used to represent integer status values with the value restricted to those in an enumeration"""

    def __init__(
        self,
    ) -> None:
        self.stVal: BehaviourModeKind_2025a = BehaviourModeKind_2025a(5)  # Value of the data
        self.q: Quality_2025a = Quality_2025a()  # Quality of the value in 'stVal'
        self.t: datetime | None = (
            None  # Timestamp of the last change or update event of 'stVal' or the last change of value in 'q'
        )
