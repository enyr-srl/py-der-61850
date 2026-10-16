from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a


class BCR_2025a(DOType):
    def __init__(
        self,
    ) -> None:

        # DataAttribute for status
        self.actVal: int = (
            0  # 	Binary counter status represented as an integer value; wraps to 0 at the maximum or minimum value of INT64.
        )
        self.q: Quality_2025a = Quality_2025a()  # Quality of the value in 'mxVal
        self.t: datetime | None = None  # Timestamp of the last change of value in 'actVal'
