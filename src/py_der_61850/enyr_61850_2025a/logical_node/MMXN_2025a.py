from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.MV_2025a import MV_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class MMXN_2025a(LNodeType):
    """This logical node is used for calculation of currents, voltages, powers and impedances in a system where voltages and currents are not phase-related, mainly for operative applications."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Measured and metered values
        self.Amp: MV_2025a = MV_2025a()  # Non-phase-related AC rms current.
        self.Volt: MV_2025a = MV_2025a()  # Non-phase-related AC rms voltage.
        self.Watt: MV_2025a = MV_2025a()  # Non-phase-related AC real power.

    def __call__(
        self,
    ) -> None:
        pass




