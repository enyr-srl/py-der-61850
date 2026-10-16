from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a


class MV_2025a(DOType):
    """This common data class shall be used to represent measured values."""

    def __init__(
        self,
    ) -> None:
        # Measured attributes
        self.mag: float = 0.0  # Magnitude
        self.q: Quality_2025a = Quality_2025a()  # Quality of the data in 'mag'
        self.t: datetime | None = (
            None  # Timestamp of the last change or update event of 'mag' or the last change of value in 'q'
        )

        # Substitution
        self.subEna: bool = False  #  Used to enable and disable substitution
        self.subMag: float = 0.0  # Value used to substitute 'Mag'.
        self.subQ: Quality_2025a = Quality_2025a()  # Value used to substitute 'q'

    def __call__(self) -> None:
        """ Se `subEna` è attivo, la sostituzione forza `mag` e `q` ai valori di
          sostituzione.
        """

        if self.subEna and self.subMag != self.mag:
            self.mag = self.subMag
            self.t = datetime.now()
            self.q = self.subQ
        return