from datetime import datetime, timedelta

from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a


class TES_2025a(DOType):
    """This data class manages a TimeSerie"""

    def __init__(
        self,
    ) -> None:

        # Setting information
        self.t: datetime | None = None  # timestamp of the first value sampled
        self.smpRate: timedelta = timedelta(minutes=15) 
        self.smpNum: int = 0

        # Status information
        self.val: list = []  # List of object indicated by sourceRef, recorder every samplePeriod
        self.q: list[Quality_2025a] = []  # List of quality to identify the quality of each record
