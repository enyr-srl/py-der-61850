from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_DERUnitKind_2025a import ENG_DERUnitKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_PhaseKind_2025a import ENG_PhaseKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_DERStateKind_2025a import ENS_DERStateKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.INS_2025a import INS_2025a
from py_der_61850.enyr_61850_2025a.data_objects.MV_2025a import MV_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DECP_2025a import ORG_DECP_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DGEN_2025a import ORG_DGEN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DPVA_2025a import ORG_DPVA_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DSTO_2025a import ORG_DSTO_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DGEN_2025a(LNodeType):
    """The DGEN logical node defines the actual connected and operational state of a DER generating unit, including aggregations of generating units. It inherits nameplate and operational characteristics, and includes the commands that cause it to change state. It also reflects the generating unit's responses to external events that cause a change of state (DERState)."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.OpTmsRs: INS_2025a = (
            INS_2025a()
        )  # Total time generator has operated – re-settable: accumulated time since the last time the counter was reset
        self.DEROpSt: ENS_DERStateKind_2025a = (
            ENS_DERStateKind_2025a()
        )  # Current state of operation of the distributed energy resource
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Measured and metered values
        self.SelfSvcWh: MV_2025a = MV_2025a()  # Actual self service energy used

        # Settings nameplate rating
        self.WMaxRtg: ASG_2025a = ASG_2025a()  # Nameplate maximum active generation power rating at unity power factor
        self.VMaxRtg: ASG_2025a = ASG_2025a()  # Maximum voltage rating

        # Settings
        self.WMax: ASG_2025a = ASG_2025a()  # Setting for maximum active power
        self.WRmp: ASG_2025a = (
            ASG_2025a()
        )  # Default ramp rate for changes in active power: percentage of WMax per second
        self.VMax: ASG_2025a = ASG_2025a()  # Setting for maximum voltage operational rating
        self.PhsConnType: ENG_PhaseKind_2025a = ENG_PhaseKind_2025a()  # Phase type of electrical connection of the DER
        self.DERTyp: ENG_DERUnitKind_2025a = ENG_DERUnitKind_2025a()  # Type of DER

        self.InclGn: ORG_DGEN_2025a = ORG_DGEN_2025a()  # Included generator. This DO points to an instance of DGEN
        self.InclSto: ORG_DSTO_2025a = ORG_DSTO_2025a()  # Included storage. This DO points to an instance of STO
        self.OutEcpRef: ORG_DECP_2025a = (
            ORG_DECP_2025a()
        )  # Reference to ECP directly connected at the output of the DER, the "plug" part. Note : The power management function ECP associated to this same resource will refer to the "socket" part.
        self.DERUnit: ORG_DPVA_2025a = ORG_DPVA_2025a()

    def __call__(
        self,
    ) -> None:
        pass