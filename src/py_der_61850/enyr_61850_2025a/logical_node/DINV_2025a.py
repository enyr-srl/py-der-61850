from py_der_61850.enyr_61850_2025a.data_objects.APC_2025a import APC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DINV_2025a(LNodeType):
    """The DPVA logical node support PV array characteristics. The photovoltaics array characteristics describe the configuration of the PV array. The logical node may be used to provide configuration information on the number of strings and panels or the number of sub-arrays in parallel. (Note that if the strings are individually controlled, the array characteristic is the same as string. In other word, a string becomes an array by itself)."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Settings
        self.WRtg: ASG_2025a = ASG_2025a()  # Rated active power of the inverter
        
        # Controls
        self.WSpt: APC_2025a = APC_2025a()  # Active power setpoint of the inverter
