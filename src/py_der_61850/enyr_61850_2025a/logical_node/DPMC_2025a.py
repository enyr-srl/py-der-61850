from datetime import datetime

from loguru import logger

from py_der_61850.enyr_61850_2025a.data_objects.ORS_2025a import ORS_2025a
from py_der_61850.enyr_61850_2025a.data_objects.APC_2025a import APC_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DSTO_2025a import ORG_DSTO_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DWFL_2025a import ORG_DWFL_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DPMC_2025a(LNodeType):
    """The DER power management capability is basically a “black box” component that acts as the intelligence for managing DERs. Just like the other components of DERs, it can be hierarchical, with higher level power management systems managing lower level power management systems. The power management functions generally include applications that can use the input from the DER resources to assess situations and provide feedback to the DER resources in the form of modifying the settings, requests, or commands in order to meet specified “goals”. These goals could come from an upper level power management function, operational functions, and DER operator input, each associated with different priorities"""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Controls
        self.WSpt1: APC_2025a = (
            APC_2025a()
        )  # Active power setpoint. Its mxVal attribute reflects the value of the setpoint that is requested.
        self.WSpt2: APC_2025a = (
            APC_2025a()
        )  # Active power setpoint. Its mxVal attribute reflects the value of the setpoint that is requested.
        self.DifWSpt1: APC_2025a = (
            APC_2025a()
        )  # Active differential power setpoint. Its mxVal attribute reflects the value of the setpoint that is requested.

        # Settings
        self.DERRef: ORG_DSTO_2025a = ORG_DSTO_2025a()  # Reference to the DER resource LN (a child of DERResourceLN)
        self.FctRef1: ORG_DWFL_2025a = ORG_DWFL_2025a()

    @staticmethod
    def _propagate_quality(target: APC_2025a, source: object) -> None:
        source_q = getattr(source, "q", None)
        source_t = getattr(source, "t", None)

        if source_q is None:
            target.q.validity = ValidityKind_2025a.invalid
        else:
            target.q.validity = source_q.validity

        target.t = source_t

    @staticmethod
    def _quality_name(apc: APC_2025a) -> str:
        return apc.q.validity.name if apc.q is not None and apc.q.validity is not None else "none"

    @staticmethod
    def _timestamp_iso(timestamp: datetime | None) -> str | None:
        return timestamp.isoformat() if timestamp is not None else None

    @staticmethod
    def _operate_with_metadata(
        target: APC_2025a,
        value: float,
        validity: ValidityKind_2025a,
        timestamp: datetime | None,
    ) -> None:
        target.Operate(value)
        target.q.validity = validity
        target.t = timestamp

    def __call__(
        self,
    ) -> None:
        selected_wspt: APC_2025a
        final_wspt = APC_2025a()

        self.WSpt1.Operate(self.FctRef1.setSrcRef.FolWRef.mag)
        self._propagate_quality(self.WSpt1, self.FctRef1.setSrcRef.FolWRef)

        if self.WSpt2.q.validity == ValidityKind_2025a.good: 
            selected_wspt = self.WSpt2
            selected_source = "cloud_wspt2"
            if self.WSpt2.t is not None:
                final_wspt.t = self.WSpt2.t
            self.DERRef.setSrcRef.LocSta.Operate(False) # controllo remoto
        else:
            selected_wspt = self.WSpt1
            selected_source = "rule_based_wspt1"
            if self.WSpt1.t is not None:
                final_wspt.t = self.WSpt1.t
            self.DERRef.setSrcRef.LocSta.Operate(True) # controllo locale

        selected_timestamp = selected_wspt.t

        logger.info(
            "[DPMC SETPOINT SOURCE] source={} "
            "WSpt2(value={}, q={}, t={}) "
            "WSpt1(value={}, q={}, t={})",
            selected_source,
            self.WSpt2.mxVal,
            self._quality_name(self.WSpt2),
            self._timestamp_iso(self.WSpt2.t),
            self.WSpt1.mxVal,
            self._quality_name(self.WSpt1),
            self._timestamp_iso(self.WSpt1.t),
        )

        if selected_wspt.q.validity != ValidityKind_2025a.good:
            final_wspt.Operate(0.0)
        # discharge
        elif selected_wspt.mxVal > 0.0:
            logger.debug("DPMC_2025a: Discharge active power setpoint")
            if (
                self.DERRef.setSrcRef.SocWh.mag
                > self.DERRef.setSrcRef.UseWh.setMag * self.DERRef.setSrcRef.UseWhMinPct.setMag / 100.0
            ):
                final_wspt.Operate(min(
                    selected_wspt.mxVal, self.DERRef.setSrcRef.DschWMax.setMag
                ))
            else:
                final_wspt.Operate(0.0)
        # charge
        else:
            logger.debug("DPMC_2025a: Charge active power setpoint")
            if (
                self.DERRef.setSrcRef.SocWh.mag
                < self.DERRef.setSrcRef.UseWh.setMag * self.DERRef.setSrcRef.UseWhMaxPct.setMag / 100.0
            ):
                final_wspt.Operate(max(
                    selected_wspt.mxVal, self.DERRef.setSrcRef.ChaWMax.setMag
                ))  
            else:
                final_wspt.Operate(0.0)

        final_wspt.q.validity = selected_wspt.q.validity
        final_wspt.t = selected_timestamp
        logger.debug(f"DPMC_2025a: Setting active power setpoint to {final_wspt.mxVal}")

        if final_wspt.q.validity != ValidityKind_2025a.good:
            active_target = "none"
            self._operate_with_metadata(
                self.DERRef.setSrcRef.ChaWSpt,
                0.0,
                ValidityKind_2025a.invalid,
                final_wspt.t,
            )
            self._operate_with_metadata(
                self.DERRef.setSrcRef.DschWSpt,
                0.0,
                ValidityKind_2025a.invalid,
                final_wspt.t,
            )
        elif final_wspt.mxVal > 0:
            active_target = "DschWSpt"
            self._operate_with_metadata(
                self.DERRef.setSrcRef.ChaWSpt,
                0,
                ValidityKind_2025a.invalid,
                final_wspt.t,
            )
            self._operate_with_metadata(
                self.DERRef.setSrcRef.DschWSpt,
                final_wspt.mxVal,
                final_wspt.q.validity,
                final_wspt.t,
            )
        else:
            active_target = "ChaWSpt"
            self._operate_with_metadata(
                self.DERRef.setSrcRef.ChaWSpt,
                final_wspt.mxVal,
                final_wspt.q.validity,
                final_wspt.t,
            )
            self._operate_with_metadata(
                self.DERRef.setSrcRef.DschWSpt,
                0,
                ValidityKind_2025a.invalid,
                final_wspt.t,
            )

        logger.info(
            "[DPMC SETPOINT FINAL] source={} active_target={} "
            "final(value={}, q={}, t={}) "
            "ChaWSpt(value={}, q={}, t={}) "
            "DschWSpt(value={}, q={}, t={})",
            selected_source,
            active_target,
            final_wspt.mxVal,
            self._quality_name(final_wspt),
            self._timestamp_iso(final_wspt.t),
            self.DERRef.setSrcRef.ChaWSpt.mxVal,
            self._quality_name(self.DERRef.setSrcRef.ChaWSpt),
            self._timestamp_iso(self.DERRef.setSrcRef.ChaWSpt.t),
            self.DERRef.setSrcRef.DschWSpt.mxVal,
            self._quality_name(self.DERRef.setSrcRef.DschWSpt),
            self._timestamp_iso(self.DERRef.setSrcRef.DschWSpt.t),
        )
