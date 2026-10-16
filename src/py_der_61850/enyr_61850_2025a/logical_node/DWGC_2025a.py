from py_der_61850.enyr_61850_2025a.data_objects.APC_2025a import APC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.MV_2025a import MV_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DSTO_2025a import ORG_DSTO_2025a
from py_der_61850.enyr_61850_2025a.data_objects.SPG_2025a import SPG_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class Enyr_DWGC_2025a(LNodeType):
    """The Set Active Power operational function (DWGC) is used to set a target active power value (generating or consuming) at the Referenced ECP that the DER should achieve. Although similar to AGC in that the DER ramps to the active power target, this function may be enabled and the target set by any authorized entity without any contractual characteristics or limitations imposed by AGC."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Measured and metered values
        self.ReqW: MV_2025a = (
            MV_2025a()  # Requested active power resulting from the function. Quality attribute shall be invalid when function is not active.
        )

        # Controls
        self.WSpt: APC_2025a = (
            APC_2025a()
        )  # Active power setpoint. Its mxVal attribute reflects the value of the setpoint that is requested.

        # Settings
        self.RmpRteUse: SPG_2025a = (
            SPG_2025a()
        )  # Use ramp rates limit. True = limited to ramp rates ; False = Not limited to ramp rates
        self.InEcpRef: ORG_DSTO_2025a = (
            ORG_DSTO_2025a()
        )  # Referenced ECP which is the source of the measurement used by the DER mode. It consists of the index or address of the appropriate LN DECP. This address may be within the DER, or within a proxy of ECP, or within a device at the ECP.
