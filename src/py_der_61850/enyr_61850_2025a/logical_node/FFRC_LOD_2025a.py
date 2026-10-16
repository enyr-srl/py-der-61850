import logging
import math
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class FFRC_LOD_2025a(LNodeType):
    """This Logical Node is responsible for making the necessary forecasts as input to the DPMC_ERAB
    regarding the electricity consumption of each utility.
    """

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)
        # Status information
        self.LodEnTotFrcs: dict[str, TES_2025a] = {}  # load forecast time series per each user
        self.LodEnTotTes: dict[str, TES_2025a] = {}  # load forecast time series per each user

        self.FrcsSmpNum: int = 4 * 24 * 1
        self.FrcsSmpRate: timedelta = timedelta(minutes=15)
        self.TesSmpNum: int = 4 * 24 * 7
        self.TesSmpRate: timedelta = timedelta(minutes=15)
        self.LodOutlierIqrFactor: float = 3.0
        self.MinReferenceCoverageRatio: float = 0.75

        self.Holidays: set[date] = set()
        self._logger = logging.getLogger(__name__)

    def __call__(self) -> None:
        now = self._now()
        forecast_start = self._next_quarter_hour(now)
        forecast_date = forecast_start.date()
        target_category = self._day_category(forecast_date)

        for user_id, history_series in self.LodEnTotTes.items():
            self._sanitize_series_values(history_series, user_id)
            history_map, fallback_value = self._build_history(history_series)
            sample_rate = history_series.smpRate or self.FrcsSmpRate
            tod_profile = self._build_time_of_day_profile(history_map)

            if not history_map:
                forecast_values = [None] * self.FrcsSmpNum
                qualities = [self._make_quality(ValidityKind_2025a.invalid) for _ in range(self.FrcsSmpNum)]
            else:
                reference_start, matches_target_category = self._find_reference_period(
                    history_series,
                    history_map,
                    forecast_start,
                    target_category,
                    sample_rate,
                )

                sorted_history = sorted(history_map.keys())
                fallback_validity = (
                    ValidityKind_2025a.questionable if fallback_value is not None else ValidityKind_2025a.invalid
                )
                forecast_values = []
                qualities = []
                remaining = self.FrcsSmpNum
                day_offset = 0
                steps_per_day = int(timedelta(days=1) / sample_rate)
                while remaining > 0:
                    day_steps = min(remaining, steps_per_day)
                    day_forecast_start = forecast_start + timedelta(days=day_offset)
                    day_target_category = self._day_category(day_forecast_start.date())
                    day_reference_start, day_matches_target = self._find_reference_period(
                        history_series,
                        history_map,
                        day_forecast_start,
                        day_target_category,
                        sample_rate,
                    )
                    if day_reference_start is None:
                        for step in range(day_steps):
                            slot_time = day_forecast_start + step * sample_rate
                            profile_value = tod_profile.get((slot_time.hour, slot_time.minute))
                            value_to_use: Any = profile_value if profile_value is not None else fallback_value
                            slot_validity = (
                                ValidityKind_2025a.questionable if value_to_use is not None else fallback_validity
                            )
                            forecast_values.append(value_to_use)
                            qualities.append(self._make_quality(slot_validity))
                    else:
                        for step in range(day_steps):
                            reference_time = day_reference_start + step * sample_rate
                            value, validity = self._resolve_forecast_value(
                                history_map,
                                sorted_history,
                                reference_time,
                                fallback_value,
                                day_matches_target,
                            )
                            forecast_values.append(value)
                            qualities.append(self._make_quality(validity))
                    remaining -= day_steps
                    day_offset += 1

            # Fill any remaining None values with nearest valid value
            forecast_values, qualities = self._fill_none_values(forecast_values, qualities)

            # Robustness: never emit an all-invalid forecast when usable history exists.
            # Backfill any residual non-finite slot from the time-of-day profile (or the last
            # known value), downgrading its quality to questionable. A truly empty history (no
            # finite samples at all) still yields an invalid forecast.
            if tod_profile or fallback_value is not None:
                for index in range(len(forecast_values)):
                    if self._is_finite_series_value(forecast_values[index]):
                        continue
                    slot_time = forecast_start + index * sample_rate
                    backfill = tod_profile.get((slot_time.hour, slot_time.minute), fallback_value)
                    if backfill is None:
                        backfill = fallback_value
                    if backfill is not None:
                        forecast_values[index] = backfill
                        qualities[index] = self._make_quality(ValidityKind_2025a.questionable)

            target_series = self.LodEnTotFrcs.setdefault(user_id, TES_2025a())
            target_series.t = forecast_start
            target_series.smpRate = self.FrcsSmpRate
            target_series.smpNum = len(forecast_values)
            target_series.val = forecast_values
            target_series.q = qualities

    def _build_history(self, series: TES_2025a) -> tuple[Dict[datetime, Any], Any]:
        if series.t is None:
            return {}, None

        history: Dict[datetime, Any] = {}
        current_time = series.t
        sample_rate = series.smpRate or self.FrcsSmpRate

        fallback_value: Any = None
        for value in series.val:
            if self._is_finite_series_value(value):
                history[current_time] = value
                fallback_value = value
            current_time += sample_rate

        return history, fallback_value

    def _build_time_of_day_profile(self, history: Dict[datetime, Any]) -> Dict[tuple[int, int], float]:
        """Average finite history by time-of-day (hour, minute).

        Used as a *shaped* fallback when no same-category reference day has sufficient coverage
        (cold start, sparse or gappy history): far better than a flat last-value line, and it
        keeps the forecast finite/questionable instead of collapsing to invalid.
        """
        buckets: Dict[tuple[int, int], list[float]] = {}
        for moment, value in history.items():
            if self._is_finite_series_value(value):
                buckets.setdefault((moment.hour, moment.minute), []).append(float(value))
        return {key: sum(values) / len(values) for key, values in buckets.items()}

    def _find_reference_period(
        self,
        series: TES_2025a,
        history: Dict[datetime, Any],
        forecast_start: datetime,
        target_category: str,
        sample_rate: timedelta,
    ) -> tuple[datetime | None, bool]:
        if not history:
            return None, False

        tzinfo = series.t.tzinfo if series.t else timezone.utc
        available_dates = {moment.date() for moment in history.keys()}
        if not available_dates:
            return None, False

        min_available_date = min(available_dates)
        fallback_reference: datetime | None = None
        fallback_matches_target = False

        for candidate_date, matches_target in self._iter_reference_candidate_dates(
            forecast_start.date(),
            min_available_date,
            target_category,
        ):
            reference_start = self._align_reference_start(candidate_date, forecast_start, tzinfo)  # type: ignore[arg-type]
            if not self._has_sufficient_reference_coverage(history, reference_start, sample_rate):
                continue
            if matches_target:
                return reference_start, True
            if fallback_reference is None:
                fallback_reference = reference_start
                fallback_matches_target = False

        if fallback_reference is not None:
            return fallback_reference, fallback_matches_target

        return None, False

    def _iter_reference_candidate_dates(
        self,
        forecast_date: date,
        min_available_date: date,
        target_category: str,
    ):
        seen_dates: set[date] = set()

        if target_category == "weekday":
            target_weekday = forecast_date.weekday()
            candidate_date = forecast_date - timedelta(days=7)
            while candidate_date >= min_available_date:
                if candidate_date.weekday() == target_weekday and self._day_category(candidate_date) == "weekday":
                    seen_dates.add(candidate_date)
                    yield candidate_date, True
                candidate_date -= timedelta(days=7)
        else:
            candidate_date = forecast_date - timedelta(days=1)
            while candidate_date >= min_available_date:
                if self._day_category(candidate_date) == target_category:
                    seen_dates.add(candidate_date)
                    yield candidate_date, True
                candidate_date -= timedelta(days=1)

        if target_category == "weekday":
            candidate_date = forecast_date - timedelta(days=1)
            while candidate_date >= min_available_date:
                if candidate_date not in seen_dates and self._day_category(candidate_date) == "weekday":
                    seen_dates.add(candidate_date)
                    yield candidate_date, False
                candidate_date -= timedelta(days=1)

        candidate_date = forecast_date - timedelta(days=1)
        while candidate_date >= min_available_date:
            if candidate_date not in seen_dates:
                yield candidate_date, False
            candidate_date -= timedelta(days=1)

    def _align_reference_start(self, candidate_date: date, forecast_start: datetime, tzinfo: timezone) -> datetime:
        reference_start = datetime.combine(candidate_date, forecast_start.time(), tzinfo=tzinfo)
        return reference_start

    def _has_sufficient_reference_coverage(
        self,
        history: Dict[datetime, Any],
        reference_start: datetime,
        sample_rate: timedelta,
    ) -> bool:
        available_samples = 0
        for offset in range(self.FrcsSmpNum):
            moment = reference_start + offset * sample_rate
            if moment in history:
                available_samples += 1
        required_samples = max(1, math.ceil(self.FrcsSmpNum * self.MinReferenceCoverageRatio))
        return available_samples >= required_samples

    def _day_category(self, target_date: date) -> str:
        if target_date in self.Holidays or target_date.weekday() == 6:
            return "holiday"
        if target_date.weekday() == 5:
            return "saturday"
        return "weekday"

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _next_quarter_hour(self, reference: datetime) -> datetime:
        has_fractional_seconds = reference.second != 0 or reference.microsecond != 0
        aligned = reference.replace(second=0, microsecond=0)
        remainder = aligned.minute % 15

        if remainder == 0 and not has_fractional_seconds:
            return aligned

        minutes_to_add = (15 - remainder) % 15
        if minutes_to_add == 0:
            minutes_to_add = 15

        return aligned + timedelta(minutes=minutes_to_add)

    def _find_fallback_value_at_time(
        self,
        history: Dict[datetime, Any],
        start_time: datetime,
    ) -> Any | None:
        """Looks for a value at the same time of day, going backwards from start_time."""
        if not history:
            return None

        min_history_time = min(history.keys())
        current_time = start_time - timedelta(days=1)
        while current_time >= min_history_time:
            if current_time in history:
                return history[current_time]
            current_time -= timedelta(days=1)
        return None

    def _resolve_forecast_value(
        self,
        history: Dict[datetime, Any],
        sorted_history: list[datetime],
        target_time: datetime,
        fallback_value: Any,
        matches_target_category: bool,
    ) -> tuple[Any, ValidityKind_2025a]:
        if target_time in history:
            validity = ValidityKind_2025a.good if matches_target_category else ValidityKind_2025a.questionable
            return history[target_time], validity

        fallback_at_time = self._find_fallback_value_at_time(history, target_time)
        if fallback_at_time is not None:
            return fallback_at_time, ValidityKind_2025a.questionable

        interpolated = self._interpolate_value(sorted_history, history, target_time)
        if interpolated is not None:
            return interpolated, ValidityKind_2025a.questionable

        if fallback_value is not None:
            return fallback_value, ValidityKind_2025a.questionable

        return None, ValidityKind_2025a.invalid

    def _interpolate_value(
        self,
        sorted_history: list[datetime],
        history: Dict[datetime, Any],
        target_time: datetime,
    ) -> Any:
        index = bisect_left(sorted_history, target_time)

        previous_time = sorted_history[index - 1] if index > 0 else None
        next_time = sorted_history[index] if index < len(sorted_history) else None

        previous_value = history.get(previous_time) if previous_time is not None else None
        next_value = history.get(next_time) if next_time is not None else None

        if previous_time is not None and next_time is not None:
            return self._linear_interpolate(previous_time, previous_value, next_time, next_value, target_time)

        if previous_time is not None:
            return previous_value

        if next_time is not None:
            return next_value

        return None

    def _linear_interpolate(
        self,
        previous_time: datetime,
        previous_value: Any,
        next_time: datetime,
        next_value: Any,
        target_time: datetime,
    ) -> Any:
        if not self._is_finite_series_value(previous_value) or not self._is_finite_series_value(next_value):
            return previous_value if self._is_finite_series_value(previous_value) else next_value

        total_seconds = (next_time - previous_time).total_seconds()
        if total_seconds == 0:
            return previous_value

        ratio = (target_time - previous_time).total_seconds() / total_seconds

        if isinstance(previous_value, (int, float)) and isinstance(next_value, (int, float)):
            return float(previous_value) + ratio * (float(next_value) - float(previous_value))

        return previous_value if ratio < 0.5 else next_value

    def _make_quality(self, validity: ValidityKind_2025a) -> Quality_2025a:
        quality = Quality_2025a()
        quality.validity = validity
        return quality

    def _fill_none_values(
        self,
        values: list[Any],
        qualities: list[Quality_2025a],
    ) -> tuple[list[Any], list[Quality_2025a]]:
        """Replace None values with the nearest valid value (previous or next).

        Updates quality to 'questionable' for filled values.
        """
        if not values:
            return values, qualities

        filled_values = values.copy()
        filled_qualities = qualities.copy()
        n = len(filled_values)

        for i in range(n):
            if self._is_finite_series_value(filled_values[i]):
                continue

            # Find previous valid value
            prev_value = None
            for j in range(i - 1, -1, -1):
                if self._is_finite_series_value(filled_values[j]):
                    prev_value = filled_values[j]
                    break

            # Find next valid value
            next_value = None
            for j in range(i + 1, n):
                if self._is_finite_series_value(filled_values[j]):
                    next_value = filled_values[j]
                    break

            # Use previous value if available, otherwise next
            if prev_value is not None:
                filled_values[i] = prev_value
                filled_qualities[i] = self._make_quality(ValidityKind_2025a.questionable)
            elif next_value is not None:
                filled_values[i] = next_value
                filled_qualities[i] = self._make_quality(ValidityKind_2025a.questionable)
            # If both are None, leave as None (will be caught by validity check)

        return filled_values, filled_qualities

    @staticmethod
    def _is_finite_series_value(value: Any) -> bool:
        if value is None:
            return False
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _sanitize_series_values(self, series: TES_2025a, user_id: str | None = None) -> None:
        negative_values = sorted(
            float(value) for value in series.val if self._is_finite_series_value(value) and float(value) < 0.0
        )
        negative_lower_bound = self._lower_iqr_fence(negative_values)

        removed_markers: list[str] = []
        sample_rate = series.smpRate or self.FrcsSmpRate
        current_time = series.t

        for index, value in enumerate(series.val):
            if not self._is_finite_series_value(value):
                self._invalidate_series_sample(series, index)
            else:
                numeric_value = float(value)
                if numeric_value > 0.0:
                    self._invalidate_series_sample(series, index)
                    removed_markers.append(current_time.isoformat() if current_time is not None else f"index {index}")
                elif negative_lower_bound is not None and numeric_value < negative_lower_bound:
                    self._invalidate_series_sample(series, index)
                    removed_markers.append(current_time.isoformat() if current_time is not None else f"index {index}")

            if current_time is not None:
                current_time += sample_rate

        if removed_markers and user_id is not None:
            shown_markers = removed_markers[:5]
            suffix = "..." if len(removed_markers) > 5 else ""
            self._logger.warning(
                "[FFRC_LOD] Removed %d anomalous load samples for user '%s' at %s%s",
                len(removed_markers),
                user_id,
                shown_markers,
                suffix,
            )

    def _invalidate_series_sample(self, series: TES_2025a, index: int) -> None:
        series.val[index] = None
        if index < len(series.q):
            series.q[index].validity = ValidityKind_2025a.invalid
            return

        while len(series.q) < index:
            series.q.append(self._make_quality(ValidityKind_2025a.good))
        series.q.append(self._make_quality(ValidityKind_2025a.invalid))

    def _lower_iqr_fence(self, sorted_values: list[float]) -> float | None:
        if len(sorted_values) < 4:
            return None

        q1 = self._percentile(sorted_values, 0.25)
        q3 = self._percentile(sorted_values, 0.75)
        iqr = q3 - q1
        if iqr <= 0.0:
            return q1 - max(abs(q1) * 0.25, 1e-6)
        return q1 - self.LodOutlierIqrFactor * iqr

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: float) -> float:
        if not sorted_values:
            raise ValueError("Cannot compute percentile of an empty sequence.")

        index = (len(sorted_values) - 1) * percentile
        lower_index = math.floor(index)
        upper_index = math.ceil(index)
        if lower_index == upper_index:
            return sorted_values[lower_index]

        lower_value = sorted_values[lower_index]
        upper_value = sorted_values[upper_index]
        weight = index - lower_index
        return lower_value + (upper_value - lower_value) * weight
