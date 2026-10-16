from bisect import bisect_left
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


ROME_TZ = ZoneInfo("Europe/Rome")


class FFRC_DAM_2025a(LNodeType):
    """This Logical Node is responsible for making the necessary forecasts as input to the DPMC_ERAB regarding future electricity prices in the day-ahead market"""

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)

        # Status information
        self.DamPrcFrcs: dict[str, TES_2025a] = {}  # day ahead market price forecast time serie per each
        self.DamPrcTes: dict[str, TES_2025a] = {}  # day ahead market price forecast time serie per each

        # Settings
        self.FrcsSmpNum: int = 4 * 24 * 1
        self.FrcsSmpRate: timedelta = timedelta(minutes=15)
        self.TesSmpNum: int = 4 * 24 * 7
        self.TesSmpRate: timedelta = timedelta(minutes=15)

        self.MrkZnIds: list = ["NORD", "CNOR", "CSUD", "SUD", "SICI", "SARD", "CALA"]
        for MrkZnId in self.MrkZnIds:
            self.DamPrcFrcs[MrkZnId] = TES_2025a()
            self.DamPrcTes[MrkZnId] = TES_2025a()

        self.Holidays: set[date] = set()

    def __call__(
        self,
    ) -> None:
        now = self._now()
        forecast_start = self._next_quarter_hour(now)
        # forecast_date = forecast_start.date()
        # target_category = self._day_category(forecast_date)

        for zone in self.MrkZnIds:
            history_series = self.DamPrcTes.get(zone)
            if history_series is None:
                # No history series at all - create invalid forecast
                target_series = self.DamPrcFrcs[zone]
                target_series.t = forecast_start
                target_series.smpRate = self.FrcsSmpRate
                target_series.smpNum = self.FrcsSmpNum
                target_series.val = [None] * self.FrcsSmpNum
                target_series.q = [self._make_quality(ValidityKind_2025a.invalid) for _ in range(self.FrcsSmpNum)]
                continue

            history_map, fallback_value = self._build_history(history_series)
            sample_rate = history_series.smpRate or self.FrcsSmpRate

            if not history_map:
                forecast_values = [None] * self.FrcsSmpNum
                qualities = [self._make_quality(ValidityKind_2025a.invalid) for _ in range(self.FrcsSmpNum)]
            else:
                sorted_history = sorted(history_map.keys())
                fallback_validity = (
                    ValidityKind_2025a.questionable if fallback_value is not None else ValidityKind_2025a.invalid
                )
                forecast_values = []
                qualities = []
                remaining = self.FrcsSmpNum
                steps_per_day = int(timedelta(days=1) / sample_rate)
                current_start = forecast_start
                while remaining > 0:
                    next_midnight = datetime.combine(
                        current_start.date() + timedelta(days=1),
                        time.min,
                        tzinfo=current_start.tzinfo,
                    )
                    steps_until_midnight = max(0, int((next_midnight - current_start) / sample_rate))
                    day_steps = steps_until_midnight if steps_until_midnight > 0 else steps_per_day
                    day_steps = min(remaining, day_steps)

                    day_forecast_date = current_start.date()
                    day_category = self._day_category(day_forecast_date)
                    reference_start, matches_target_category = self._find_reference_day(
                        history_series,
                        history_map,
                        current_start,
                        day_forecast_date,
                        day_category,
                        sample_rate,
                    )

                    if reference_start is None:
                        value_to_use: Any = fallback_value
                        forecast_values.extend([value_to_use] * day_steps)
                        qualities.extend([self._make_quality(fallback_validity)] * day_steps)
                    else:
                        for step in range(day_steps):
                            target_time = current_start + step * sample_rate
                            aligned_target_time = self._align_target_time(history_series, target_time)
                            if aligned_target_time in history_map:
                                direct_value = history_map[aligned_target_time]
                                validity = (
                                    ValidityKind_2025a.good if direct_value is not None else ValidityKind_2025a.invalid
                                )
                                forecast_values.append(direct_value)
                                qualities.append(self._make_quality(validity))
                                continue

                            reference_time = reference_start + step * sample_rate
                            value, validity = self._resolve_forecast_value(
                                history_map,
                                sorted_history,
                                reference_time,
                                fallback_value,
                                matches_target_category,
                            )
                            forecast_values.append(value)
                            qualities.append(self._make_quality(validity))

                    remaining -= day_steps
                    current_start += day_steps * sample_rate

            # Fill any remaining None values with nearest valid value
            forecast_values, qualities = self._fill_none_values(forecast_values, qualities)

            target_series = self.DamPrcFrcs[zone]
            target_series.t = forecast_start
            target_series.smpRate = self.FrcsSmpRate
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
            if filled_values[i] is not None:
                continue

            # Find previous valid value
            prev_value = None
            for j in range(i - 1, -1, -1):
                if filled_values[j] is not None:
                    prev_value = filled_values[j]
                    break

            # Find next valid value
            next_value = None
            for j in range(i + 1, n):
                if filled_values[j] is not None:
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

    def _build_history(self, series: TES_2025a) -> tuple[Dict[datetime, Any], Any]:
        if series.t is None:
            return {}, None

        history: Dict[datetime, Any] = {}
        current_time = series.t
        sample_rate = series.smpRate or self.FrcsSmpRate

        fallback_value: Any = None
        for value in series.val:
            if value is not None:
                history[current_time] = value
                fallback_value = value
            current_time += sample_rate

        return history, fallback_value

    def _find_reference_day(
        self,
        series: TES_2025a,
        history: Dict[datetime, Any],
        forecast_start: datetime,
        forecast_date: date,
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

        candidate_date = forecast_date - timedelta(days=1)
        while candidate_date >= min_available_date:
            reference_start = self._align_reference_start(series, candidate_date, forecast_start, tzinfo)  # type: ignore
            if self._has_available_samples(series, history, reference_start, sample_rate):
                category = self._day_category(candidate_date)
                if category == target_category:
                    return reference_start, True
                if fallback_reference is None:
                    fallback_reference = reference_start
                    fallback_matches_target = False
            candidate_date -= timedelta(days=1)

        if fallback_reference is not None:
            return fallback_reference, fallback_matches_target

        return None, False

    def _has_available_samples(
        self,
        series: TES_2025a,
        history: Dict[datetime, Any],
        reference_start: datetime,
        sample_rate: timedelta,
    ) -> bool:
        for step in range(self.FrcsSmpNum):
            moment = reference_start + step * sample_rate
            aligned_moment = self._align_target_time(series, moment)
            if aligned_moment in history:
                return True
        return False

    def _day_category(self, target_date: date) -> str:
        if target_date in self.Holidays or target_date.weekday() == 6:
            return "holiday"
        if target_date.weekday() == 5:
            return "saturday"
        return "weekday"

    def _now(self) -> datetime:
        # DAM slots are defined in the Italian market timezone and the cached
        # TES history is stored as local wall-clock timestamps.
        return datetime.now(ROME_TZ)

    def _next_quarter_hour(self, reference: datetime) -> datetime:
        aligned = reference.replace(second=0, microsecond=0)
        remainder = aligned.minute % 15

        minutes_to_add = (15 - remainder) % 15
        if minutes_to_add == 0:
            minutes_to_add = 15

        return aligned + timedelta(minutes=minutes_to_add)

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
        if previous_value is None or next_value is None:
            return previous_value if previous_value is not None else next_value

        total_seconds = (next_time - previous_time).total_seconds()
        if total_seconds == 0:
            return previous_value

        ratio = (target_time - previous_time).total_seconds() / total_seconds

        if isinstance(previous_value, (int, float)) and isinstance(next_value, (int, float)):
            return float(previous_value) + ratio * (float(next_value) - float(previous_value))

        return previous_value if ratio < 0.5 else next_value

    def _align_reference_start(
        self,
        series: TES_2025a,
        candidate_date: date,
        forecast_start: datetime,
        tzinfo: timezone,
    ) -> datetime:
        reference_time = forecast_start.time()
        reference_start = datetime.combine(candidate_date, reference_time, tzinfo=tzinfo)
        if series.t is not None and series.t.tzinfo is None:
            return reference_start.replace(tzinfo=None)
        return reference_start

    def _align_target_time(self, series: TES_2025a, target_time: datetime) -> datetime:
        series_timestamp = series.t
        series_tz = series_timestamp.tzinfo if series_timestamp else None
        if series_tz is None:
            return target_time.replace(tzinfo=None)
        if target_time.tzinfo is None:
            return target_time.replace(tzinfo=series_tz)
        return target_time.astimezone(series_tz)

    def _make_quality(self, validity: ValidityKind_2025a) -> Quality_2025a:
        quality = Quality_2025a()
        quality.validity = validity
        return quality
