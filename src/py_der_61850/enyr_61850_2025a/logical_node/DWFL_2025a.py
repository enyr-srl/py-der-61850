from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.MV_2025a import MV_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DECP_2025a import ORG_DECP_2025a
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DWFL_2025a(LNodeType):
    """The Active Power Following operational function (DWFL) has the purpose of maintaining the power level at the DER output at a level that tracks the level of a reference signal. In the case of load following, the output of the DER active power output rises as the consumption of the reference load rises. In the case of generation following, the DER active power absorbed increases as the output of the reference generation increases. The LN identifies the active power threshold for starting to follow the measured (or calculated) active power at the Referenced ECP. If the threshold value is negative, consumption is to be followed. If the threshold value is positive, generation is to be followed. A percentage of following is included. for counteracting the active power after the threshold has been reached."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Measured and metered values
        self.FolWRef: MV_2025a = MV_2025a()  # Referenced Active Power Measurement that the should be followed

        # Settings
        self.FolWTgt: ASG_2025a = (
            ASG_2025a()
        )  # 	Active Power value setting that sets the target net value from the combination of the followed and following DER
        self.WThr: ASG_2025a = (
            ASG_2025a()
        )  # Active Power Threshold that triggers the start of following when the referenced active power is equal to or greater than the threshold.
        self.WPct: ASG_2025a = (
            ASG_2025a()
        )  # Active Power Ratio (percentage) of the active power discharged or charged to the referenced active power

        self.InEcpRef1: ORG_DECP_2025a = (
            ORG_DECP_2025a()
        )  # Referenced ECP which is the source of the measurement used by the DER mode. It consists of the index or address of the appropriate LN DECP. This address may be within the DER, or within a proxy of ECP, or within a device at the ECP.

        self.InEcpRef2: ORG_DECP_2025a = (
            ORG_DECP_2025a()
        )  # Referenced ECP which is the source of the measurement used by the DER mode. It consists of the index or address of the appropriate LN DECP. This address may be within the DER, or within a proxy of ECP, or within a device at the ECP.

    def __call__(
        self,
    ) -> None:
        watt_inputs = []
        for ecp_ref in (self.InEcpRef1, self.InEcpRef2):
            ecp = getattr(ecp_ref, "setSrcRef", None)
            mmxn_ref = getattr(ecp, "ElcMsRef1", None) if ecp is not None else None
            mmxn = getattr(mmxn_ref, "setSrcRef", None) if mmxn_ref is not None else None
            watt = getattr(mmxn, "Watt", None) if mmxn is not None else None

            if (
                watt is None
                or watt.t is None
                or watt.q.validity != ValidityKind_2025a.good
            ):
                self.FolWRef.mag = 0.0
                self.FolWRef.q.validity = ValidityKind_2025a.invalid
                self.FolWRef.t = None
                return

            watt_inputs.append(watt)

        folwref_mag = -(sum(watt.mag for watt in watt_inputs))

        if abs(folwref_mag - self.FolWTgt.setMag) > self.WThr.setMag:
            self.FolWRef.mag = self.WPct.setMag * (folwref_mag - self.FolWTgt.setMag) / 100.0
        else:
            self.FolWRef.mag = 0.0

        self.FolWRef.q.validity = ValidityKind_2025a.good
        self.FolWRef.t = max(watt.t for watt in watt_inputs if watt.t is not None)
