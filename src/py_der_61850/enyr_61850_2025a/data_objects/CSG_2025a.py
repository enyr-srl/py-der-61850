from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Unit_SIUnitKind_2025a import Unit_SIUnitKind_2025a


class CSG_2025a(DOType):
    """Abstract type, holding attributes common to curve points and curve settings. Using data objects of this type allows two-dimensional and three-dimensional curves to be defined, as well as polygons (two-dimensional surfaces) and three-dimensional surfaces."""

    def __init__(
        self,
    ) -> None:
        # DataAttribute for setting
        self.numPts: int = 0  # Actual number of elements used in 'crvPts[]'.
        self.crvPts: list = [[], [], []]  # The array with the points specifying a curve shape.

        # DataAttribute for configuration, description and extension
        self.xUnits: Unit_SIUnitKind_2025a = Unit_SIUnitKind_2025a()  # Unit of the x-axis of a curve.
        self.yUnits: Unit_SIUnitKind_2025a = Unit_SIUnitKind_2025a()  # Unit of the y-axis of a curve.
        self.zUnits: Unit_SIUnitKind_2025a = Unit_SIUnitKind_2025a()  # Unit of the z-axis of a curve.
        self.xD: str = ""  # Description of the value of the x-axis of a curve.
        self.yD: str = ""  # Description of the value of the y-axis of a curve.
        self.zD: str = ""  # Description of the value of the y-axis of a curve.
        self.maxPts: int = 0  # Maximum number of elements available in 'crvPts[]'.
