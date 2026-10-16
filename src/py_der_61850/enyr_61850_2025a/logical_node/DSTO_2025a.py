from py_der_61850.enyr_61850_2025a.data_objects.SPC_2025a import SPC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.APC_2025a import APC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.CSG_2025a import CSG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_ChargeSourceKind_2025a import ENG_ChargeSourceKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_DERUnitKind_2025a import ENG_DERUnitKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENG_PhaseKind_2025a import ENG_PhaseKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_DERStateKind_2025a import ENS_DERStateKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.INS_2025a import INS_2025a
from py_der_61850.enyr_61850_2025a.data_objects.MV_2025a import MV_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DECP_2025a import ORG_DECP_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DSTO_2025a import ORG_DSTO_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DSTO_2025a(LNodeType):
    """This logical node contains information related to monitoring and controlling energy storage functions and states. It can apply to single element or to aggregated one."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.DEROpSt: ENS_DERStateKind_2025a = (
            ENS_DERStateKind_2025a()
        )  # Current state of operation of the distributed energy resource
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node
        self.ChaCycCnt: INS_2025a = INS_2025a()  # Count of the number of equivalent full charge cycles

        # Measured and metered values
        self.SocWh: MV_2025a = MV_2025a()  # Actual state of charge expressed in Wh
        self.UseSocPct: MV_2025a = MV_2025a()  # Actual state of charge expressed in Wh

        self.AvlChaW: MV_2025a = MV_2025a()  # Available charging power
        self.AvlDschW: MV_2025a = MV_2025a()  # Available discharging power
        self.EffWh: MV_2025a = (
            MV_2025a()
        )  # Effective actual total energy capacity (in Wh) provided by the storage resource. Due to degradation, the amount may be less than the rated total energy capacity (WhRtg)

        # Controls
        self.LocSta : SPC_2025a = SPC_2025a()  # Local/Remote control status
        self.ChaWSpt: APC_2025a = (
            APC_2025a()
        )  # Active power setpoint. Its mxVal attribute reflects the value of the setpoint that is requested
        self.DschWSpt: APC_2025a = (
            APC_2025a()
        )  # Active power setpoint. Its mxVal attribute reflects the value of the setpoint that is requested

        # Settings nameplate rating
        self.WhRtg: ASG_2025a = ASG_2025a()  # Nameplate energy storage capacity rating in Wh
        self.WhMaxRtg: ASG_2025a = (
            ASG_2025a()
        )  # Nameplate maximum amount of energy (in Wh) to be stored in the storage resource for e.g. supporting long life and avoid faster degradation
        self.WhMinRtg: ASG_2025a = (
            ASG_2025a()
        )  # Nameplate minimum amount of energy (in Wh) to be retained in the storage resource for e.g. supporting long life and avoid faster degradation or to ensure a reserve of energy stored for emergencies and other purposes
        self.ChaWMaxRtg: ASG_2025a = ASG_2025a()  # Nameplate maximum active power rating while charging
        self.DschMaxRtg: ASG_2025a = ASG_2025a()  # Nameplate maximum active power rating while discharging
        self.ChaSrcRtg: ENG_ChargeSourceKind_2025a = (
            ENG_ChargeSourceKind_2025a()
        )  # Net Energy Metering (NEM) Policy Mode which establishes whether the DER qualifies as renewable. Mode A = Storage may charge from the grid but may not discharge to the grid (acts only as load). Mode B = Storage may not charge from the grid but may discharge to the grid (charges from local energy source). Mode C = Storage may charge or discharge from the grid at will / in response to commands for location where there are no NEM integrity concerns

        # Settings
        self.UseWh: ASG_2025a = ASG_2025a()  # Operational setpoint for usable energy storage capacity in Wh
        self.UseWhMaxPct: ASG_2025a = (
            ASG_2025a()
        )  # The energy reserve level above which the storage system may be only be charged in emergency situations, expressed as a percentage of the usable capacity, UseWh
        self.UseWhMinPct: ASG_2025a = (
            ASG_2025a()
        )  # The energy reserve level below which the storage system may be only be discharged in emergency situations, expressed as a percentage of the usable capacity, UseWh
        self.ChaWMax: ASG_2025a = ASG_2025a()  # Maximum active power while charging
        self.DschWMax: ASG_2025a = ASG_2025a()  # Maximum active power while discharging
        self.ChaWRmp: ASG_2025a = (
            ASG_2025a()
        )  # Default ramp rate for changes in active power: percentage of WMax per second while charging
        self.DschWRmp: ASG_2025a = (
            ASG_2025a()
        )  #  Default ramp rate for changes in active power: percentage of WMax per second while discharging
        self.ChaSrc: ENG_ChargeSourceKind_2025a = (
            ENG_ChargeSourceKind_2025a()
        )  # Net Energy Metering (NEM) Policy Mode which establishes whether the DER qualifies as renewable. Mode A = Storage may charge from the grid but may not discharge to the grid (acts only as load). Mode B = Storage may not charge from the grid but may discharge to the grid (charges from local energy source). Mode C = Storage may charge or discharge from the grid at will / in response to commands for location where there are no NEM integrity concerns
        self.ChaEfcPct: ASG_2025a = ASG_2025a()  # Charging efficiency [% over SoC]
        self.DschEfcPct: ASG_2025a = ASG_2025a()  # Discharging efficiency [% over SoC]
        self.PhsConnType: ENG_PhaseKind_2025a = ENG_PhaseKind_2025a()  # Phase type of electrical connection of the DER
        self.DERTyp: ENG_DERUnitKind_2025a = ENG_DERUnitKind_2025a()  # Type of DER

        self.InclSto: ORG_DSTO_2025a = (
            ORG_DSTO_2025a()
        )  # References to Included storage resource, which could be virtual, aggregated, or physical. This DO points to an instance of DSTO
        self.OutEcpRef: ORG_DECP_2025a = (
            ORG_DECP_2025a()
        )  # Reference to ECP directly connected at the output of the DER, the "plug" part. Note : The power management function ECP associated to this same resource will refer to the "socket" part.

    def __call__(
        self,
    ) -> None:

        self.SocWh.mag = self.UseSocPct.mag / 100 * self.UseWh.setMag
