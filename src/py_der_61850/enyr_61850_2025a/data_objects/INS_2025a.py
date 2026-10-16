from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a


class INS_2025a(DOType):
    """This common data class shall be used to represent integer status values."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for status
        self.stVal: int = 0  # Vale of the data
        self.q: Quality_2025a = Quality_2025a()  # Quality of the data in 'stVal'
        self.t: datetime | None = (
            None  # Timestamp of the last change or update event of 'stVal' or the last change of value in 'q'
        )

        # Substitution
        self.subEna: bool = False  #  Used to enable and disable substitution
        self.subVal: int = 0  # Value used to substitute 'stVal'.
        self.subQ: Quality_2025a = Quality_2025a()  # Value used to substitute 'q'
