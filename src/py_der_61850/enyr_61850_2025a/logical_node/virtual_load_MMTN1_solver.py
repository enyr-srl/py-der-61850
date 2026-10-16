import logging
from collections.abc import Sequence
from typing import cast

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.BCR_2025a import BCR_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_DMDR_2025a import ORG_DMDR_2025a
from py_der_61850.enyr_61850_2025a.logical_node.DMDR_2025a import DMDR_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class virtual_load_MMTN1_solver(LNodeType):
    """
    Risolve virtualemnte il contatore di energia al load come differenza dagli altri
    """

    _SMALL_INCREASE_CLAMP_WH = 50
    # Oltre questa soglia un aumento del contatore (che dovrebbe solo decrescere) non e'
    # rumore ma un RESET/ri-base dei contatori sorgente (es. riconnessione FusionSolar):
    # un consumo di piu' di qualche kWh in 15 min e' fisicamente impossibile. In quel caso
    # NON applichiamo il salto (che introdurrebbe uno spike da milioni di Wh nella serie di
    # carico e la renderebbe inservibile per la previsione): teniamo la baseline e assorbiamo
    # il ri-base in un offset, cosi' il conteggio cumulativo prosegue in modo continuo.
    _RESET_JUMP_THRESHOLD_WH = 5000

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)
        self._logger = logging.getLogger(__name__)

        self.DERRef: ORG_DMDR_2025a = ORG_DMDR_2025a()  # Reference to the DMDR
        self._last_addend_values: dict[str, int | None] = {
            "pv_sup": None,
            "bess_sup": None,
            "bess_dmd": None,
            "pod_dmd": None,
            "pod_sup": None,
        }
        self._last_applied_load_value: int | None = None
        # Offset cumulativo che assorbe i reset/ri-base dei contatori sorgente, cosi' il
        # contatore di carico virtuale resta continuo attraverso le riconnessioni.
        self._reset_offset: int = 0

    def __call__(
        self,
    ) -> None:
        DER = self.DERRef.setSrcRef
        DER = cast(DMDR_2025a, DER)
        load_mmtn_node = self._resolve_path(
            DER,
            (
                "InclLod",
                "setSrcRef",
                "OutEcpRef",
                "setSrcRef",
                "ElcMsRef2",
                "setSrcRef",
            ),
        )

        load_mmtn = self._resolve_required_counter(
            DER,
            (
                "InclLod",
                "setSrcRef",
                "OutEcpRef",
                "setSrcRef",
                "ElcMsRef2",
                "setSrcRef",
                "DmdWh",
            ),
            "load_dmd",
        )
        pv_sup = self._resolve_optional_counter(
            DER,
            (
                "InclGn",
                "setSrcRef",
                "InclGn",
                "setSrcRef",
                "OutEcpRef",
                "setSrcRef",
                "ElcMsRef2",
                "setSrcRef",
                "SupWh",
            ),
        )
        bess_sup = self._resolve_optional_counter(
            DER,
            (
                "InclSto",
                "setSrcRef",
                "OutEcpRef",
                "setSrcRef",
                "ElcMsRef2",
                "setSrcRef",
                "SupWh",
            ),
        )
        bess_dmd = self._resolve_optional_counter(
            DER,
            (
                "InclSto",
                "setSrcRef",
                "OutEcpRef",
                "setSrcRef",
                "ElcMsRef2",
                "setSrcRef",
                "DmdWh",
            ),
        )
        pod_dmd = self._resolve_required_counter(
            DER,
            ("OutEcpRef", "setSrcRef", "ElcMsRef2", "setSrcRef", "DmdWh"),
            "pod_dmd",
        )
        pod_sup = (
            self._resolve_required_counter(
                DER,
                ("OutEcpRef", "setSrcRef", "ElcMsRef2", "setSrcRef", "SupWh"),
                "pod_sup",
            )
            if self._is_pod_sup_declared()
            else None
        )

        addend_sources: dict[str, tuple[BCR_2025a | None, int]] = {
            "pv_sup": (pv_sup, -1),
            "bess_sup": (bess_sup, -1),
            "bess_dmd": (bess_dmd, -1),
            "pod_dmd": (pod_dmd, 1),
            "pod_sup": (pod_sup, 1),
        }
        addends = {
            name: (counter, coefficient)
            for name, (counter, coefficient) in addend_sources.items()
            if counter is not None
        }

        # Signed convention:
        # - SupWh is positive and increasing
        # - DmdWh is negative and decreasing
        current_load_val = load_mmtn.actVal
        raw_computed_load_val = sum(coefficient * counter.actVal for counter, coefficient in addends.values())
        # L'offset accumulato assorbe i reset gia' visti: la serie di carico prosegue continua.
        computed_load_val = raw_computed_load_val + self._reset_offset
        monotonic_reference = (
            self._last_applied_load_value if self._last_applied_load_value is not None else current_load_val
        )
        monotonic_violation_detected = (
            self._last_applied_load_value is not None and computed_load_val > monotonic_reference
        )
        applied_load_val = computed_load_val
        clamp_small_positive_increase = False
        reset_absorbed = False
        increase = computed_load_val - monotonic_reference
        if monotonic_violation_detected and increase > self._RESET_JUMP_THRESHOLD_WH:
            # Reset/ri-base dei contatori sorgente: non e' consumo. Teniamo la baseline
            # (zero consumo in questo slot) e assorbiamo il salto nell'offset, cosi' i cicli
            # successivi ripartono dal livello corretto invece di congelarsi.
            self._reset_offset += monotonic_reference - computed_load_val
            applied_load_val = monotonic_reference
            reset_absorbed = True
        elif monotonic_violation_detected and increase <= self._SMALL_INCREASE_CLAMP_WH:
            applied_load_val = monotonic_reference
            clamp_small_positive_increase = True

        load_mmtn.actVal = applied_load_val
        # Aggiorna qualità e timestamp del DmdWh virtuale
        quality_sources = [counter for counter, _coefficient in addends.values()]
        q_values = [counter.q.validity for counter in quality_sources]
        if ValidityKind_2025a.invalid in q_values:
            q_res = ValidityKind_2025a.invalid
        elif ValidityKind_2025a.questionable in q_values:
            q_res = ValidityKind_2025a.questionable
        else:
            q_res = ValidityKind_2025a.good
        if monotonic_violation_detected and q_res == ValidityKind_2025a.good:
            q_res = ValidityKind_2025a.questionable
        t_res = max((counter.t for counter in quality_sources if counter.t is not None), default=None)
        load_mmtn.q.validity = q_res
        load_mmtn.t = t_res
        if monotonic_violation_detected:
            self._log_load_increase(
                addend_sources=addend_sources,
                current_load_val=current_load_val,
                computed_load_val=computed_load_val,
                applied_load_val=applied_load_val,
                increase=increase,
                clamped=clamp_small_positive_increase,
                reset_absorbed=reset_absorbed,
            )
        self._last_applied_load_value = applied_load_val
        self._update_addend_cache(
            {
                name: counter.actVal if counter is not None else None
                for name, (counter, _coefficient) in addend_sources.items()
            }
        )
        self._validate_mmtn_node(load_mmtn_node)

    def _update_addend_cache(self, values: dict[str, int | None]) -> None:
        for name, value in values.items():
            self._last_addend_values[name] = value

    def _log_load_increase(
        self,
        *,
        addend_sources: dict[str, tuple[BCR_2025a | None, int]],
        current_load_val: int,
        computed_load_val: int,
        applied_load_val: int,
        increase: int,
        clamped: bool,
        reset_absorbed: bool = False,
    ) -> None:
        contributions: list[str] = []
        source_issues: list[str] = []
        for name, (counter, coefficient) in addend_sources.items():
            current_value = counter.actVal if counter is not None else None
            previous_value = self._last_addend_values.get(name)
            if current_value is None or previous_value is None:
                continue
            source_delta = current_value - previous_value
            load_delta = coefficient * source_delta
            contributions.append(f"{name}:source_delta={source_delta},load_delta={load_delta}")
            expected_direction = self._expected_source_delta_direction(name)
            if expected_direction is not None and not expected_direction(source_delta):
                source_issues.append(f"{name}:delta={source_delta} expected {self._expected_delta_text(name)}")

        if reset_absorbed:
            action = f"absorbed counter reset (> {self._RESET_JUMP_THRESHOLD_WH} Wh) into offset; held baseline"
        elif clamped:
            action = f"clamped small increase <= {self._SMALL_INCREASE_CLAMP_WH} Wh"
        else:
            action = "applied large increase as questionable"
        self._logger.warning(
            "virtual_load_MMTN1_solver detected load DmdWh increase: "
            "last_applied=%s current=%s computed=%s applied=%s increase=%s action=%s contributions=[%s] source_issues=[%s]",
            self._last_applied_load_value,
            current_load_val,
            computed_load_val,
            applied_load_val,
            increase,
            action,
            ", ".join(contributions) if contributions else "n/a",
            ", ".join(source_issues) if source_issues else "none",
        )

    @staticmethod
    def _resolve_path(root: object, path: Sequence[str]) -> object | None:
        current: object | None = root
        for attr in path:
            if current is None:
                return None
            current = getattr(current, attr, None)
        return current

    def _resolve_optional_counter(self, root: object, path: Sequence[str]) -> BCR_2025a | None:
        counter = self._resolve_path(root, path)
        return cast(BCR_2025a | None, counter)

    def _resolve_required_counter(self, root: object, path: Sequence[str], label: str) -> BCR_2025a:
        counter = self._resolve_optional_counter(root, path)
        if counter is None:
            raise ValueError(f"virtual_load_MMTN1_solver missing required counter '{label}'.")
        return counter

    def _is_pod_sup_declared(self) -> bool:
        if not getattr(self._visitor, "_user_config", None):
            return True
        return self._visitor.has_data_attribute(
            device_id="pod",
            ln_id="MMTN1",
            do_id="SupWh",
            da_id="actVal",
        )

    @staticmethod
    def _expected_source_delta_direction(name: str):
        if name in {"pv_sup", "bess_sup", "pod_sup"}:
            return lambda delta: delta >= 0
        if name in {"bess_dmd", "pod_dmd"}:
            return lambda delta: delta <= 0
        return None

    @staticmethod
    def _expected_delta_text(name: str) -> str:
        if name in {"pv_sup", "bess_sup", "pod_sup"}:
            return ">= 0"
        if name in {"bess_dmd", "pod_dmd"}:
            return "<= 0"
        return "n/a"

    @staticmethod
    def _validate_mmtn_node(mmtn_node: object | None) -> None:
        validate = getattr(mmtn_node, "validate_invariants", None)
        if callable(validate):
            validate()
