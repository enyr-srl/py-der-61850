from bisect import bisect_left
from datetime import datetime, timedelta, timezone
import logging
import math
from typing import Any, Dict

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class FFRC_GN_2025a(LNodeType):
    """This Logical Node is responsible for making the necessary forecasts as input to the DPMC_ERAB regarding the electricity generation of each utility."""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.GnEnTotFrcs: dict[str, TES_2025a] = {}  # load forecast time serie per each user
        self.HorInsolFrcs: dict[str, TES_2025a] = {}
        self.GnEnTotTes: dict[str, TES_2025a] = {}
        self.HorInsolTes: dict[str, TES_2025a] = {}

        # Settings
        self.FrcsSmpNum: int = 4 * 24 * 1
        self.FrcsSmpRate: timedelta = timedelta(minutes=15)
        self.TesSmpNum: int = 4 * 24 * 30
        self.TesSmpRate: timedelta = timedelta(minutes=15)
        self.GnOutlierMinInsolation: float = 50.0
        self.GnOutlierIqrFactor: float = 3.0
        self.GnLowRatioMinInsolation: float = 150.0
        self.GnLowRatioQ75Factor: float = 0.35
        self.GnLowRatioMinSamples: int = 16

        self._logger = logging.getLogger(__name__)

    def __call__(
        self,
    ) -> None:
        now = self._now()
        forecast_start = self._next_quarter_hour(now)

        for user_id, history_series in self.HorInsolTes.items():
            self._sanitize_series_values(history_series)
            history_map, sorted_history = self._build_history(history_series)
            sample_rate = history_series.smpRate or self.FrcsSmpRate

            forecast_values: list[Any]
            qualities: list[Quality_2025a]
            if not history_map:
                forecast_values = [None] * self.FrcsSmpNum
                qualities = [self._make_quality(ValidityKind_2025a.invalid) for _ in range(self.FrcsSmpNum)]
            else:
                fallback_value = history_map[sorted_history[-1]]
                forecast_values = []
                qualities = []
                for step in range(self.FrcsSmpNum):
                    target_time = forecast_start + step * sample_rate
                    direct_value = self._direct_sample(history_series, target_time, sample_rate)
                    if direct_value is not None:
                        if direct_value is self._MISSING_SAMPLE:
                            value, validity = self._select_forecast_value(
                                history_map,
                                sorted_history,
                                target_time,
                                sample_rate,
                                fallback_value,
                            )
                        else:
                            value = direct_value
                            validity = ValidityKind_2025a.good if value is not None else ValidityKind_2025a.invalid
                    else:
                        value, validity = self._select_forecast_value(
                            history_map,
                            sorted_history,
                            target_time,
                            sample_rate,
                            fallback_value,
                        )
                    forecast_values.append(value)
                    qualities.append(self._make_quality(validity))

            # Fill any remaining None values with nearest valid value
            forecast_values, qualities = self._fill_none_values(forecast_values, qualities)

            target_series = self.HorInsolFrcs.setdefault(user_id, TES_2025a())
            target_series.t = forecast_start
            target_series.smpRate = self.FrcsSmpRate
            target_series.smpNum = len(forecast_values)
            target_series.val = forecast_values
            target_series.q = qualities

        self._update_generation_forecast(forecast_start)

    def _build_history(self, series: TES_2025a) -> tuple[Dict[datetime, Any], list[datetime]]:
        if series.t is None:
            return {}, []

        history: Dict[datetime, Any] = {}
        timestamps: list[datetime] = []
        current_time = series.t
        sample_rate = series.smpRate or self.FrcsSmpRate

        for value in series.val:
            if self._is_finite_series_value(value):
                history[current_time] = value
                timestamps.append(current_time)
            current_time += sample_rate

        return history, timestamps

    def _update_generation_forecast(self, forecast_start: datetime) -> None:
        user_ids = set(self.HorInsolTes.keys()) | set(self.GnEnTotTes.keys())

        for user_id in user_ids:
            insolation_history = self.HorInsolTes.get(user_id)
            generation_history = self.GnEnTotTes.get(user_id)
            insolation_forecast = self.HorInsolFrcs.get(user_id)

            target_series = self.GnEnTotFrcs.setdefault(user_id, TES_2025a())
            target_series.t = forecast_start
            target_series.smpRate = self.FrcsSmpRate

            if insolation_history is None or generation_history is None or insolation_forecast is None:
                target_series.smpNum = self.FrcsSmpNum
                target_series.val = [None] * self.FrcsSmpNum
                target_series.q = [self._make_quality(ValidityKind_2025a.invalid) for _ in range(self.FrcsSmpNum)]
                continue

            self._sanitize_series_values(insolation_history)
            self._sanitize_series_values(generation_history)
            self._sanitize_series_values(insolation_forecast)
            generation_history_for_model = self._copy_series(generation_history)
            self._fill_generation_gaps_with_zero(insolation_history, generation_history_for_model)
            model = self._fit_generation_model(insolation_history, generation_history_for_model, user_id)
            if model is None:
                target_series.smpNum = self.FrcsSmpNum
                target_series.val = [None] * self.FrcsSmpNum
                target_series.q = [self._make_quality(ValidityKind_2025a.invalid) for _ in range(self.FrcsSmpNum)]
                continue

            slope, intercept, max_training_input = model
            forecast_values: list[Any] = []
            qualities: list[Quality_2025a] = []

            for insolation_value in insolation_forecast.val:
                if not self._is_finite_series_value(insolation_value):
                    forecast_values.append(None)
                    qualities.append(self._make_quality(ValidityKind_2025a.invalid))
                    continue

                numeric_insolation = float(insolation_value)
                generated = max(0.0, intercept + slope * numeric_insolation)
                if self._is_effectively_zero(numeric_insolation):
                    generated = 0.0
                forecast_values.append(generated)

                validity = (
                    ValidityKind_2025a.questionable
                    if numeric_insolation > max_training_input
                    else ValidityKind_2025a.good
                )
                qualities.append(self._make_quality(validity))

            # Fill any remaining None values with nearest valid value
            forecast_values, qualities = self._fill_none_values(forecast_values, qualities)

            target_series.smpNum = len(forecast_values)
            target_series.val = forecast_values
            target_series.q = qualities

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

    def _fit_generation_model(
        self,
        insolation_series: TES_2025a,
        generation_series: TES_2025a,
        user_id: str | None = None,
    ) -> tuple[float, float, float] | None:
        insolation_history, _ = self._build_history(insolation_series)
        generation_history, _ = self._build_history(generation_series)

        if not insolation_history or not generation_history:
            return None

        common_timestamps = sorted(set(insolation_history.keys()) & set(generation_history.keys()))
        if len(common_timestamps) < 2:
            return None

        samples = [
            (
                timestamp,
                float(insolation_history[timestamp]),
                float(generation_history[timestamp]),
            )
            for timestamp in common_timestamps
        ]
        samples, removed_timestamps = self._filter_generation_training_samples(samples)
        if removed_timestamps and user_id is not None:
            shown_timestamps = [timestamp.isoformat() for timestamp in removed_timestamps[:5]]
            suffix = "..." if len(removed_timestamps) > 5 else ""
            self._logger.warning(
                "[FFRC_GN] Removed %d anomalous generation samples from model fit for user '%s' at %s%s",
                len(removed_timestamps),
                user_id,
                shown_timestamps,
                suffix,
            )

        xs = [sample[1] for sample in samples]
        ys = [sample[2] for sample in samples]

        if len(xs) < 2:
            return None

        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)

        variance_x = sum((x - mean_x) ** 2 for x in xs)
        if variance_x == 0:
            slope = 0.0
            intercept = max(0.0, mean_y)
        else:
            covariance = sum((x - mean_x) * (y - mean_y) for _, x, y in samples)
            slope = covariance / variance_x
            if slope < 0:
                slope = 0.0
            intercept = mean_y - slope * mean_x
            if intercept < 0:
                intercept = 0.0

        max_training_input = max(xs)
        return slope, intercept, max_training_input

    def _filter_generation_training_samples(
        self,
        samples: list[tuple[datetime, float, float]],
    ) -> tuple[list[tuple[datetime, float, float]], list[datetime]]:
        if not samples:
            return [], []

        positive_generation = sorted(generation for _, _, generation in samples if generation > 0.0)
        low_irradiance_generation = sorted(
            generation
            for _, insolation, generation in samples
            if 0.0 <= insolation <= self.GnOutlierMinInsolation and generation >= 0.0
        )

        positive_generation_upper_bound = self._upper_iqr_fence(positive_generation)
        low_irradiance_upper_bound = self._upper_iqr_fence(low_irradiance_generation)

        upper_filtered_samples: list[tuple[datetime, float, float]] = []
        removed_timestamps: list[datetime] = []

        for timestamp, insolation, generation in samples:
            if insolation < 0.0 or generation < 0.0:
                removed_timestamps.append(timestamp)
                continue

            if 0.0 <= insolation <= self.GnOutlierMinInsolation:
                upper_bound = low_irradiance_upper_bound
                if upper_bound is None:
                    upper_bound = positive_generation_upper_bound
                if upper_bound is not None and generation > upper_bound:
                    removed_timestamps.append(timestamp)
                    continue
                upper_filtered_samples.append((timestamp, insolation, generation))
                continue

            if positive_generation_upper_bound is not None and generation > positive_generation_upper_bound:
                removed_timestamps.append(timestamp)
                continue

            upper_filtered_samples.append((timestamp, insolation, generation))

        daytime_positive_ratios = sorted(
            generation / insolation
            for _, insolation, generation in upper_filtered_samples
            if insolation >= self.GnLowRatioMinInsolation and generation > 0.0
        )
        low_ratio_threshold = None
        if len(daytime_positive_ratios) >= self.GnLowRatioMinSamples:
            low_ratio_threshold = self._percentile(daytime_positive_ratios, 0.75) * self.GnLowRatioQ75Factor

        if low_ratio_threshold is None:
            return upper_filtered_samples, removed_timestamps

        filtered_samples: list[tuple[datetime, float, float]] = []
        for timestamp, insolation, generation in upper_filtered_samples:
            if insolation >= self.GnLowRatioMinInsolation and generation / insolation < low_ratio_threshold:
                removed_timestamps.append(timestamp)
                continue
            filtered_samples.append((timestamp, insolation, generation))

        return filtered_samples, removed_timestamps

    def _copy_series(self, source: TES_2025a) -> TES_2025a:
        cloned = TES_2025a()
        cloned.t = source.t
        cloned.smpRate = source.smpRate
        cloned.smpNum = source.smpNum
        cloned.val = list(source.val)
        cloned.q = [self._make_quality(quality.validity) for quality in source.q]
        return cloned

    def _upper_iqr_fence(self, sorted_values: list[float]) -> float | None:
        if len(sorted_values) < 4:
            return None

        q1 = self._percentile(sorted_values, 0.25)
        q3 = self._percentile(sorted_values, 0.75)
        iqr = q3 - q1
        if iqr <= 0.0:
            return q3 + max(abs(q3) * 0.25, 1e-6)
        return q3 + self.GnOutlierIqrFactor * iqr

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

    def _select_forecast_value(
        self,
        history: Dict[datetime, Any],
        sorted_history: list[datetime],
        target_time: datetime,
        sample_rate: timedelta,
        fallback_value: Any,
    ) -> tuple[Any, ValidityKind_2025a]:
        if target_time in history:
            return history[target_time], ValidityKind_2025a.good

        interpolated = self._interpolate_value(sorted_history, history, target_time)
        if interpolated is not None:
            return interpolated, ValidityKind_2025a.questionable

        repeated = self._repeat_latest_pattern(history, sorted_history, target_time, sample_rate)
        if repeated is not None:
            return repeated, ValidityKind_2025a.questionable

        if fallback_value is not None:
            return fallback_value, ValidityKind_2025a.questionable

        return None, ValidityKind_2025a.invalid

    def _fill_generation_gaps_with_zero(self, insolation_series: TES_2025a, generation_series: TES_2025a) -> None:
        if (
            insolation_series is None
            or generation_series is None
            or insolation_series.t is None
            or generation_series.t is None
        ):
            return

        insolation_rate = insolation_series.smpRate or self.FrcsSmpRate
        generation_rate = generation_series.smpRate or self.FrcsSmpRate
        if insolation_rate != generation_rate:
            return

        insolation_map: Dict[datetime, Any] = {}
        timestamp = insolation_series.t
        for value in insolation_series.val:
            insolation_map[timestamp] = value if self._is_finite_series_value(value) else None
            timestamp += insolation_rate

        timestamp = generation_series.t
        for index, value in enumerate(generation_series.val):
            if self._is_finite_series_value(value):
                timestamp += generation_rate
                continue

            irradiance_value = insolation_map.get(timestamp)
            if self._is_effectively_zero(irradiance_value):
                generation_series.val[index] = 0.0
                if 0 <= index < len(generation_series.q):
                    generation_series.q[index].validity = ValidityKind_2025a.good
            timestamp += generation_rate

    def _is_effectively_zero(self, value: Any, tolerance: float = 1e-6) -> bool:
        if not self._is_finite_series_value(value):
            return False
        try:
            return abs(float(value)) <= tolerance
        except (TypeError, ValueError):
            return False

    def _repeat_latest_pattern(
        self,
        history: Dict[datetime, Any],
        sorted_history: list[datetime],
        target_time: datetime,
        sample_rate: timedelta,
    ) -> Any:
        if not sorted_history:
            return None

        earliest_time = sorted_history[0]
        candidate = target_time - timedelta(days=1)
        while candidate >= earliest_time:
            if candidate in history:
                return history[candidate]
            candidate -= timedelta(days=1)

        candidate = target_time - sample_rate
        while candidate >= earliest_time:
            if candidate in history:
                return history[candidate]
            candidate -= sample_rate

        return None

    def _interpolate_value(
        self,
        sorted_history: list[datetime],
        history: Dict[datetime, Any],
        target_time: datetime,
    ) -> Any:
        index = bisect_left(sorted_history, target_time)

        previous_time = sorted_history[index - 1] if index > 0 else None
        next_time = sorted_history[index] if index < len(sorted_history) else None

        prev_value = history.get(previous_time) if previous_time is not None else None
        next_value = history.get(next_time) if next_time is not None else None

        if previous_time is not None and next_time is not None:
            return self._linear_interpolate(previous_time, prev_value, next_time, next_value, target_time)

        if previous_time is not None and next_time is None:
            # No future sample to interpolate with; let the caller fall back to pattern reuse
            return None

        if previous_time is None and next_time is not None:
            return next_value

        return None

    def _linear_interpolate(
        self,
        previous_time: datetime,
        prev_value: Any,
        next_time: datetime,
        next_value: Any,
        target_time: datetime,
    ) -> Any:
        if not self._is_finite_series_value(prev_value) or not self._is_finite_series_value(next_value):
            return prev_value if self._is_finite_series_value(prev_value) else next_value

        total_seconds = (next_time - previous_time).total_seconds()
        if total_seconds == 0:
            return prev_value

        ratio = (target_time - previous_time).total_seconds() / total_seconds

        if isinstance(prev_value, (int, float)) and isinstance(next_value, (int, float)):
            return float(prev_value) + ratio * (float(next_value) - float(prev_value))

        return prev_value if ratio < 0.5 else next_value

    def _make_quality(self, validity: ValidityKind_2025a) -> Quality_2025a:
        quality = Quality_2025a()
        quality.validity = validity
        return quality

    _MISSING_SAMPLE: Any = object()

    def _direct_sample(
        self,
        series: TES_2025a,
        target_time: datetime,
        sample_rate: timedelta,
    ) -> Any | None:
        if series.t is None or not series.val:
            return None
        delta = target_time - series.t
        if delta.total_seconds() < 0:
            return None
        step_index = int(delta / sample_rate)
        if step_index < 0 or step_index >= len(series.val):
            return None
        value = series.val[step_index]
        return value if self._is_finite_series_value(value) else self._MISSING_SAMPLE

    @staticmethod
    def _is_finite_series_value(value: Any) -> bool:
        if value is None:
            return False
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _sanitize_series_values(self, series: TES_2025a) -> None:
        for index, value in enumerate(series.val):
            if self._is_finite_series_value(value):
                continue
            series.val[index] = None
            if index < len(series.q):
                series.q[index].validity = ValidityKind_2025a.invalid
            else:
                while len(series.q) < index:
                    series.q.append(self._make_quality(ValidityKind_2025a.good))
                series.q.append(self._make_quality(ValidityKind_2025a.invalid))

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _next_quarter_hour(self, reference: datetime) -> datetime:
        aligned = reference.replace(second=0, microsecond=0)
        if reference == aligned:
            return aligned

        remainder = aligned.minute % 15
        minutes_to_add = (15 - remainder) % 15
        if minutes_to_add == 0:
            minutes_to_add = 15

        return aligned + timedelta(minutes=minutes_to_add)
