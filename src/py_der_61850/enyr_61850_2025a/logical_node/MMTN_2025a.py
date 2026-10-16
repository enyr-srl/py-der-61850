import logging
from collections.abc import Callable
from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.BCR_2025a import BCR_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class MMTN_2025a(LNodeType):
    """This logical node is used for calculation of currents, voltages, powers and impedances in a system where voltages and currents are not phase-related, mainly for operative applications."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)
        self._logger = logging.getLogger(__name__)

        # Status information
        self.SupWh: BCR_2025a = BCR_2025a()  # Real energy supply (default direction: towards busbar).
        self.DmdWh: BCR_2025a = BCR_2025a()  # Real energy demand (direction: from busbar).
        self.SupWhDay: BCR_2025a = BCR_2025a()  # Real energy supply (default direction: towards busbar).
        self.DmdWhDay: BCR_2025a = BCR_2025a()  # Real energy demand (direction: from busbar).

        # Cache ultimo valore giornaliero per calcolare il delta (gestione reset a fine giornata)
        self._oldSupWhDay: int = 0
        self._oldDmdWhDay: int = 0
        self._last_sign_warning_values: dict[str, int | None] = {"SupWh": None, "DmdWh": None}
        self._last_monotonic_observations: dict[str, tuple[datetime, int] | None] = {
            "SupWh": None,
            "DmdWh": None,
        }
        self._last_monotonic_warning_keys: dict[str, tuple[datetime, int, int] | None] = {
            "SupWh": None,
            "DmdWh": None,
        }
        self._bootstrap_questionable_once: set[str] = set()

    def __call__(
        self,
    ) -> None:
        self._update_total(self.SupWh, self.SupWhDay, "_oldSupWhDay")
        self._update_total(self.DmdWh, self.DmdWhDay, "_oldDmdWhDay")
        self._apply_bootstrap_quality_overrides()
        self.validate_invariants()

    def bootstrap_total_from_history(
        self,
        total_name: str,
        *,
        total_value: int,
        total_timestamp: datetime,
        previous_daily_value: int,
        mark_questionable: bool = False,
    ) -> None:
        total = self._get_total_counter(total_name)
        cache_attr = self._get_daily_cache_attr(total_name)

        total.actVal = total_value
        total.t = total_timestamp
        total.q.validity = ValidityKind_2025a.good
        setattr(self, cache_attr, previous_daily_value)

        if mark_questionable:
            self._bootstrap_questionable_once.add(total_name)
        else:
            self._bootstrap_questionable_once.discard(total_name)

    def validate_invariants(self) -> None:
        self._warn_if_sign_convention_violated("SupWh", self.SupWh, lambda value: value > 0, "positive")
        self._warn_if_sign_convention_violated("DmdWh", self.DmdWh, lambda value: value < 0, "negative")
        self._warn_if_monotonicity_violated(
            "SupWh",
            self.SupWh,
            lambda previous, current: current >= previous,
            "non-decreasing",
        )
        self._warn_if_monotonicity_violated(
            "DmdWh",
            self.DmdWh,
            lambda previous, current: current <= previous,
            "non-increasing",
        )

    def _update_total(self, total: BCR_2025a, daily: BCR_2025a, cache_attr: str) -> None:
        """
        Aggiorna il contatore totale con il delta del contatore giornaliero.

        - Usa il daily solo se la qualità è good e il suo timestamp è più recente di quello del totale.
        - Gestisce sia contatori positivi crescenti sia contatori negativi decrescenti.
        - Gestisce il reset giornaliero: se il valore giornaliero torna verso zero, considera il valore corrente come delta.
        """
        if daily.q.validity != ValidityKind_2025a.good:
            return
        if daily.t is None:
            return
        if total.t is not None and daily.t <= total.t:
            return

        prev = getattr(self, cache_attr)
        day_val = daily.actVal

        same_direction = prev == 0 or day_val == 0 or (day_val > 0) == (prev > 0)
        is_continuation = same_direction and abs(day_val) >= abs(prev)
        delta = day_val - prev if is_continuation else day_val

        total.actVal += delta  # delta può essere 0
        total.t = daily.t
        total.q.validity = ValidityKind_2025a.good

        setattr(self, cache_attr, day_val)

    def _warn_if_sign_convention_violated(
        self,
        attr_name: str,
        counter: BCR_2025a,
        is_valid_sign: Callable[[int], bool],
        expected_sign: str,
    ) -> None:
        if counter.q.validity != ValidityKind_2025a.good or counter.t is None:
            self._last_sign_warning_values[attr_name] = None
            return

        counter_value = counter.actVal
        if is_valid_sign(counter_value):
            self._last_sign_warning_values[attr_name] = None
            return

        if self._last_sign_warning_values[attr_name] == counter_value:
            return

        self._logger.warning(
            "MMTN sign convention violated for %s.actVal: got %s, expected %s.",
            attr_name,
            counter_value,
            expected_sign,
        )
        self._last_sign_warning_values[attr_name] = counter_value

    def _warn_if_monotonicity_violated(
        self,
        attr_name: str,
        counter: BCR_2025a,
        is_monotonic: Callable[[int, int], bool],
        expected_behavior: str,
    ) -> None:
        if counter.q.validity != ValidityKind_2025a.good or counter.t is None:
            self._last_monotonic_observations[attr_name] = None
            self._last_monotonic_warning_keys[attr_name] = None
            return

        current_observation = (counter.t, counter.actVal)
        last_observation = self._last_monotonic_observations[attr_name]

        if last_observation is None:
            self._last_monotonic_observations[attr_name] = current_observation
            self._last_monotonic_warning_keys[attr_name] = None
            return

        last_time, last_value = last_observation
        current_time, current_value = current_observation

        if current_time <= last_time:
            return

        if is_monotonic(last_value, current_value):
            self._last_monotonic_warning_keys[attr_name] = None
        else:
            warning_key = (current_time, last_value, current_value)
            if self._last_monotonic_warning_keys[attr_name] != warning_key:
                self._logger.warning(
                    "MMTN monotonicity violated for %s.actVal: previous=%s at %s, current=%s at %s, expected %s behavior.",
                    attr_name,
                    last_value,
                    last_time.isoformat(),
                    current_value,
                    current_time.isoformat(),
                    expected_behavior,
                )
                self._last_monotonic_warning_keys[attr_name] = warning_key

        self._last_monotonic_observations[attr_name] = current_observation

    def _apply_bootstrap_quality_overrides(self) -> None:
        for total_name in list(self._bootstrap_questionable_once):
            total = self._get_total_counter(total_name)
            if total.q.validity == ValidityKind_2025a.good:
                total.q.validity = ValidityKind_2025a.questionable
            self._bootstrap_questionable_once.discard(total_name)

    def _get_total_counter(self, total_name: str) -> BCR_2025a:
        total = getattr(self, total_name, None)
        if not isinstance(total, BCR_2025a):
            raise ValueError(f"Unsupported total counter '{total_name}' for MMTN bootstrap.")
        return total

    @staticmethod
    def _get_daily_cache_attr(total_name: str) -> str:
        if total_name == "SupWh":
            return "_oldSupWhDay"
        if total_name == "DmdWh":
            return "_oldDmdWhDay"
        raise ValueError(f"Unsupported total counter '{total_name}' for MMTN bootstrap.")
