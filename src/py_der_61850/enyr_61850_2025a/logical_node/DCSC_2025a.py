from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_DCSCKind_2025a import ENG_DCSCKind_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DCSC_2025a(LNodeType):
    """The ESUA logical node contains the characteristics of the specific Electrical energy Supplay Agreement related to a PCC."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Settings
        self.CnttTyp: ENG_DCSCKind_2025a = ENG_DCSCKind_2025a()
        self.VrblFee: ASG_2025a = ASG_2025a() # €/Wh
        self.FixFee: ASG_2025a = ASG_2025a() # €
        self.PctGriLos: ASG_2025a = ASG_2025a() # %
        self.VATpct: ASG_2025a = ASG_2025a() # %
        self.CnttWatt: ASG_2025a = ASG_2025a() # W
