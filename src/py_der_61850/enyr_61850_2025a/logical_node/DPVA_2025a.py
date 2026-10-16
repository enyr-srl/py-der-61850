from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.DPL_2025a import DPL_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_PVAssemblyKind_2025a import ENG_PVAssemblyKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DPVA_2025a(LNodeType):
    """The DPVA logical node support PV array characteristics. The photovoltaics array characteristics describe the configuration of the PV array. The logical node may be used to provide configuration information on the number of strings and panels or the number of sub-arrays in parallel. (Note that if the strings are individually controlled, the array characteristic is the same as string. In other word, a string becomes an array by itself)."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Descriptions
        self.EEName: DPL_2025a = (
            DPL_2025a()
        )  # Name plate of external (electrical, mechanical or communication) equipment to which the logical node is associated.

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Settings
        self.Type: ENG_PVAssemblyKind_2025a = ENG_PVAssemblyKind_2025a()  # Assembly type
        self.ArrArea: ASG_2025a = ASG_2025a()  # Array area
        self.ArrWRtg: ASG_2025a = ASG_2025a()  # Array active power rating (watts peak – watts p)
        self.Tilt: ASG_2025a = (
            ASG_2025a()
        )  # Assembly fixed tilt – degrees from horizontal (may be seasonally adjusted)
        self.Azi: ASG_2025a = ASG_2025a()  # Assembly azimuth – degrees from true north
