from py_der_61850.enyr_61850_2025a.data_objects.ENG_DERUnitKind_2025a import ENG_DERUnitKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_PhaseKind_2025a import ENG_PhaseKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_DERStateKind_2025a import ENS_DERStateKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DGEN_2025a import ORG_DGEN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DLOD_2025a import ORG_DLOD_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DMDR_2025a import ORG_DMDR_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DPCC_2025a import ORG_DPCC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DSTO_2025a import ORG_DSTO_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DMDR_2025a(LNodeType):
    """LN class to support mixed combined DER"""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node
        self.DEROpSt: ENS_DERStateKind_2025a = (
            ENS_DERStateKind_2025a()
        )  # Current state of operation of the distributed energy resource

        # Settings
        self.PhsConnType: ENG_PhaseKind_2025a = ENG_PhaseKind_2025a()  # Phase type of electrical connection of the DER
        self.DERTyp: ENG_DERUnitKind_2025a = ENG_DERUnitKind_2025a()  # Type of DER

        self.OutEcpRef: ORG_DPCC_2025a = ORG_DPCC_2025a()
        self.InclGn: ORG_DGEN_2025a = ORG_DGEN_2025a()
        self.InclSto: ORG_DSTO_2025a = ORG_DSTO_2025a()
        self.InclLod: ORG_DLOD_2025a = ORG_DLOD_2025a()

        for i in range(1, self._visitor.get_users_length() + 1):
            setattr(
                self, f"InclDER{i}", ORG_DMDR_2025a()
            )  # References to other DMDR logical nodes representing DER units
