from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DCSC_2025a import ORG_DCSC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DPRC_2025a import ORG_DPRC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_MMTN_2025a import ORG_MMTN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_MMXN_2025a import ORG_MMXN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.SPG_2025a import SPG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.VSG_2025a import VSG_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DPCC_2025a(LNodeType):
    """The DPCC logical node contains the operational characteristics of a specific Electrical Connection Point (ECP) located between the local EPS and the area EPS, called PCC."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Settings
        self.AreaEpsEcpId: VSG_2025a = VSG_2025a()  # Identification of the ECP from the Area Electric Power System
        self.VRef: ASG_2025a = (
            ASG_2025a()
        )  # Default reference voltage for functions using voltage at this ECP as input. It may be overridden by VRef setpoints in specific operational functions.
        self.RefFrm: SPG_2025a = SPG_2025a()  # True = Producer Reference Frame; False = Consumer Reference Frame

        self.AreaEpsCacerId: VSG_2025a = VSG_2025a()
        self.AreaEpsPCabId: VSG_2025a = VSG_2025a()
        self.AreaEpsMrkZnId: VSG_2025a = VSG_2025a()

        self.ElcMsRef1: ORG_MMXN_2025a = (
            ORG_MMXN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef2: ORG_MMTN_2025a = (
            ORG_MMTN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.CsmpCnttRef: ORG_DCSC_2025a = (
            ORG_DCSC_2025a()
        )  # The ESUA logical node contains the characteristics of the specific Electrical energy Supplay Agreement related to a PCC.
        self.PrdcCnttRef: ORG_DPRC_2025a = (
            ORG_DPRC_2025a()
        )  # The ESEA logical node contains the characteristics of the specific Electrical energy Selling Agreement related to a PCC.
