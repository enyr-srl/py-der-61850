from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType


class DPL_2025a(DOType):
    def __init__(
        self,
    ) -> None:

        self.vendor: str = ""  # Name of the vendor.
        self.latitude: float = 0.0  # Geographical position of device in WGS84 coordinates - latitude.
        self.longitude: float = 0.0  # Geographical position of device in WGS84 coordinates - latitude.
