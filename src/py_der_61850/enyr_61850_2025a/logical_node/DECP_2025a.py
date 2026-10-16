from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_objects.ASG_2025a import ASG_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ENS_BehaviourModeKind_2025a import ENS_BehaviourModeKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_MMTN_2025a import ORG_MMTN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_MMXN_2025a import ORG_MMXN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.SPG_2025a import SPG_2025a
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class DECP_2025a(LNodeType):
    """The DECP logical node contains the operational characteristics of the Electrical Connection Point (ECP), to be used in all other cases than the PCC case (refer to DPCC)."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.Beh: ENS_BehaviourModeKind_2025a = (
            ENS_BehaviourModeKind_2025a()
        )  # Read-only value, describing the behaviour of a domain logical node. It depends on the current operating mode of the logical node

        # Settings
        self.VRef: ASG_2025a = (
            ASG_2025a()
        )  # Default reference voltage for functions using voltage at this ECP as input. It may be overridden by VRef setpoints in specific operational functions.
        self.RefFrm: SPG_2025a = SPG_2025a()  # True = Producer Reference Frame; False = Consumer Reference Frame

        self.ElcMsRef1: ORG_MMXN_2025a = (
            ORG_MMXN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef2: ORG_MMTN_2025a = (
            ORG_MMTN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef3: ORG_MMXN_2025a = (
            ORG_MMXN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef4: ORG_MMTN_2025a = (
            ORG_MMTN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef5: ORG_MMXN_2025a = (
            ORG_MMXN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef6: ORG_MMTN_2025a = (
            ORG_MMTN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef7: ORG_MMXN_2025a = (
            ORG_MMXN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef8: ORG_MMTN_2025a = (
            ORG_MMTN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef9: ORG_MMXN_2025a = (
            ORG_MMXN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self.ElcMsRef10: ORG_MMTN_2025a = (
            ORG_MMTN_2025a()
        )  # Reference to electrical measurement/calculation function, typically MMXU, MMXN or MMDC, MMTR LN instances
        self._energy_residual_wh_by_counter_id: dict[int, float] = {}
        self._last_integration_timestamp_by_pair_id: dict[int, datetime] = {}

    def __call__(self) -> None:
        """
        Integra la potenza misurata (MMXN.Watt) nei contatori energia (MMTN SupWh/DmdWh).
        Producer reference frame:
        - Watt >= 0 => export (SupWh positivo crescente)
        - Watt < 0 => import (DmdWh negativo decrescente)
        """
        # 1. Aggrega la potenza totale dai rami (se configurati)
        self._aggregate_power_total(self.ElcMsRef1, [self.ElcMsRef3, self.ElcMsRef5, self.ElcMsRef7, self.ElcMsRef9])

        # 2. Integra potenza -> energia per ogni coppia
        self._integrate_pair(self.ElcMsRef1, self.ElcMsRef2)
        self._integrate_pair(self.ElcMsRef3, self.ElcMsRef4)
        self._integrate_pair(self.ElcMsRef5, self.ElcMsRef6)
        self._integrate_pair(self.ElcMsRef7, self.ElcMsRef8)
        self._integrate_pair(self.ElcMsRef9, self.ElcMsRef10)

        # 3. Se la potenza totale (1) non è valida, prova a ricostruire l'energia totale (2) dalla somma dei rami.
        self._fallback_energy_from_branches(self.ElcMsRef1, self.ElcMsRef2, [self.ElcMsRef4, self.ElcMsRef6, self.ElcMsRef8, self.ElcMsRef10])
        self._validate_energy_refs([self.ElcMsRef2, self.ElcMsRef4, self.ElcMsRef6, self.ElcMsRef8, self.ElcMsRef10])

    def _integrate_pair(self, mmxn_ref: ORG_MMXN_2025a, mmt_n_ref: ORG_MMTN_2025a) -> None:
        """Integra una coppia MMXN->MMTN se i riferimenti sono validi."""
        mmxn = getattr(mmxn_ref, "setSrcRef", None)
        mmt_n = getattr(mmt_n_ref, "setSrcRef", None)
        if mmxn is None or mmt_n is None:
            return

        watt = getattr(mmxn, "Watt", None)
        if watt is None:
            return

        # Usa solo potenza valida e con timestamp presente
        if watt.q.validity != ValidityKind_2025a.good or watt.t is None:
            # Non invalidare i contatori energia se la potenza manca:
            # semplicemente non integriamo questo campione.
            return

        pair_id = id(mmt_n)
        last_t = self._last_integration_timestamp_by_pair_id.get(pair_id)

        # Producer frame: segno positivo => export, negativo => import
        target = mmt_n.SupWh if watt.mag >= 0 else mmt_n.DmdWh

        # Se non abbiamo un timestamp precedente, inizializza e attendi il prossimo campione.
        # Il timestamp è per coppia MMXN/MMTN, non per contatore, così un cambio di segno
        # non integra sul nuovo verso anche il tempo in cui era attivo il verso opposto.
        if last_t is None:
            self._last_integration_timestamp_by_pair_id[pair_id] = watt.t
            target.t = watt.t
            target.q.validity = ValidityKind_2025a.good
            return

        # Timestamp deve essere nuovo rispetto all'energia
        if watt.t <= last_t:
            target.q.validity = ValidityKind_2025a.questionable
            return

        delta_ms = (watt.t - last_t).total_seconds() * 1000
        if delta_ms <= 0:
            target.q.validity = ValidityKind_2025a.questionable
            return

        # Energia in Wh (W * h); delta_ms è in millisecondi
        delta_wh = abs(watt.mag) * (delta_ms / 3_600_000.0)
        residual_key = id(target)
        total_delta_wh = self._energy_residual_wh_by_counter_id.get(residual_key, 0.0) + delta_wh
        whole_delta_wh = int(total_delta_wh)
        self._energy_residual_wh_by_counter_id[residual_key] = total_delta_wh - whole_delta_wh

        # Convenzione contatori:
        # - SupWh positivo crescente
        # - DmdWh negativo decrescente
        signed_delta = whole_delta_wh if watt.mag >= 0 else -whole_delta_wh
        target.actVal += signed_delta
        target.t = watt.t
        target.q.validity = ValidityKind_2025a.good
        self._last_integration_timestamp_by_pair_id[pair_id] = watt.t

    def _aggregate_power_total(self, total_ref: ORG_MMXN_2025a, branch_refs: list[ORG_MMXN_2025a]) -> None:
        """Imposta Watt del totale come somma dei rami configurati (producer frame)."""
        total = getattr(total_ref, "setSrcRef", None)
        if total is None or getattr(total, "Watt", None) is None:
            return

        sum_power = 0.0
        any_used = False
        any_invalid = False
        max_t = None

        for ref in branch_refs:
            mmxn = getattr(ref, "setSrcRef", None)
            if mmxn is None or getattr(mmxn, "Watt", None) is None:
                continue
            watt = mmxn.Watt
            if watt.q.validity != ValidityKind_2025a.good or watt.t is None:
                any_invalid = True
                continue
            any_used = True
            sum_power += watt.mag
            if max_t is None or watt.t > max_t:
                max_t = watt.t

        if not any_used:
            return

        total.Watt.mag = sum_power
        total.Watt.t = max_t
        total.Watt.q.validity = ValidityKind_2025a.good if not any_invalid else ValidityKind_2025a.questionable

    def _fallback_energy_from_branches(
        self,
        total_power_ref: ORG_MMXN_2025a,
        total_energy_ref: ORG_MMTN_2025a,
        branch_energy_refs: list[ORG_MMTN_2025a],
    ) -> None:
        """
        Se la potenza totale (1) non è valida, ricostruisce l'energia totale (2) sommando le energie dei rami.
        """
        total_power = getattr(total_power_ref, "setSrcRef", None)
        total_energy = getattr(total_energy_ref, "setSrcRef", None)
        if total_energy is None:
            return

        power_valid = (
            total_power is not None
            and getattr(total_power, "Watt", None) is not None
            and total_power.Watt.q.validity == ValidityKind_2025a.good
        )

        if power_valid:
            return  # abbiamo già integrato da potenza valida

        def _sum_bcr(attr: str):
            sum_val = 0
            any_used = False
            any_invalid = False
            max_t = None
            for ref in branch_energy_refs:
                mmt = getattr(ref, "setSrcRef", None)
                if mmt is None:
                    continue
                bcr = getattr(mmt, attr, None)
                if bcr is None:
                    continue
                if bcr.q.validity != ValidityKind_2025a.good or bcr.t is None:
                    any_invalid = True
                    continue
                any_used = True
                sum_val += bcr.actVal
                if max_t is None or bcr.t > max_t:
                    max_t = bcr.t
            return any_used, any_invalid, sum_val, max_t

        any_sup, sup_invalid, sup_val, sup_t = _sum_bcr("SupWh")
        if any_sup:
            total_energy.SupWh.actVal = sup_val
            total_energy.SupWh.t = sup_t
            total_energy.SupWh.q.validity = ValidityKind_2025a.good if not sup_invalid else ValidityKind_2025a.questionable

        any_dmd, dmd_invalid, dmd_val, dmd_t = _sum_bcr("DmdWh")
        if any_dmd:
            total_energy.DmdWh.actVal = dmd_val
            total_energy.DmdWh.t = dmd_t
            total_energy.DmdWh.q.validity = ValidityKind_2025a.good if not dmd_invalid else ValidityKind_2025a.questionable

    @staticmethod
    def _validate_energy_refs(energy_refs: list[ORG_MMTN_2025a]) -> None:
        for energy_ref in energy_refs:
            energy = getattr(energy_ref, "setSrcRef", None)
            validate = getattr(energy, "validate_invariants", None)
            if callable(validate):
                validate()
