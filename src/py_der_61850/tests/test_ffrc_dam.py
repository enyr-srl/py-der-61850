from datetime import date, datetime, time, timedelta, timezone
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from py_der_61850.enyr_61850_2025a.logical_node.FFRC_DAM_2025a import (
    FFRC_DAM_2025a,
    ROME_TZ,
)
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.models.config_visitor import ConfigVisitor


class TestFFRCDAMForecast(unittest.TestCase):
    def setUp(self) -> None:
        self.node = FFRC_DAM_2025a(visitor=ConfigVisitor())
        self.zone = self.node.MrkZnIds[0]
        self.sample_rate = self.node.TesSmpRate
        self.quarters_per_day = int(timedelta(days=1) / self.sample_rate)

    def test_now_uses_rome_timezone(self) -> None:
        self.assertEqual(self.node._now().tzinfo, ROME_TZ)

    def test_future_tes_values_align_with_rome_local_clock(self) -> None:
        fake_now = datetime(2024, 3, 11, 19, 44, 41, tzinfo=ZoneInfo("Europe/Rome"))
        forecast_start = self.node._next_quarter_hour(fake_now)

        start_time = datetime(2024, 3, 4, 0, 0)
        values = self._populate_tes_series(start_time, days=8)

        aligned_forecast_start = forecast_start.replace(tzinfo=None)
        steps_until_forecast = int((aligned_forecast_start - start_time) / self.sample_rate)
        available_future_steps = 8
        cutoff = steps_until_forecast + available_future_steps
        series = self.node.DamPrcTes[self.zone]
        series.val = series.val[:cutoff]
        series.smpNum = len(series.val)

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.DamPrcFrcs[self.zone]
        expected_direct = values[steps_until_forecast : steps_until_forecast + available_future_steps]
        self.assertListEqual(forecast_series.val[:available_future_steps], expected_direct)
        self.assertTrue(
            all(
                quality.validity == ValidityKind_2025a.good
                for quality in forecast_series.q[:available_future_steps]
            )
        )

    def test_weekday_uses_previous_working_day(self) -> None:
        fake_now = datetime(2024, 3, 11, 8, 30, tzinfo=timezone.utc)  # Monday

        start_time = datetime(2024, 3, 4, 0, 0, tzinfo=timezone.utc)
        values = self._populate_tes_series(start_time, days=7)

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        self._assert_forecast_matches_reference_blocks(
            fake_now,
            start_time,
            values,
            [date(2024, 3, 8), date(2024, 3, 8)],
        )

        forecast_series = self.node.DamPrcFrcs[self.zone]
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q)
        )

    def test_saturday_uses_previous_saturday(self) -> None:
        fake_now = datetime(2024, 3, 9, 10, 15, tzinfo=timezone.utc)  # Saturday

        start_time = datetime(2024, 2, 24, 0, 0, tzinfo=timezone.utc)
        values = self._populate_tes_series(start_time, days=14)

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        self._assert_forecast_matches_reference_blocks(
            fake_now,
            start_time,
            values,
            [date(2024, 3, 2), date(2024, 3, 3)],
        )

        forecast_series = self.node.DamPrcFrcs[self.zone]
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q)
        )

    def test_sunday_uses_previous_sunday(self) -> None:
        fake_now = datetime(2024, 3, 10, 12, 0, tzinfo=timezone.utc)  # Sunday

        start_time = datetime(2024, 2, 25, 0, 0, tzinfo=timezone.utc)
        values = self._populate_tes_series(start_time, days=14)

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        self._assert_forecast_matches_reference_blocks(
            fake_now,
            start_time,
            values,
            [date(2024, 3, 3), date(2024, 3, 8)],
        )

        forecast_series = self.node.DamPrcFrcs[self.zone]
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q)
        )

    def test_holiday_uses_previous_holiday_or_sunday(self) -> None:
        fake_now = datetime(2024, 4, 25, 7, 0, tzinfo=timezone.utc)  # Liberation Day (holiday)
        self.node.Holidays.update({date(2024, 4, 25), date(2024, 4, 18)})

        start_time = datetime(2024, 4, 10, 0, 0, tzinfo=timezone.utc)
        values = self._populate_tes_series(start_time, days=20)
        forecast_start = self.node._next_quarter_hour(fake_now)
        steps_until_forecast = int((forecast_start - start_time) / self.sample_rate)
        series = self.node.DamPrcTes[self.zone]
        series.val = series.val[:steps_until_forecast]
        series.smpNum = len(series.val)

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        history_series = self.node.DamPrcTes[self.zone]
        history_map, _ = self.node._build_history(history_series)
        sample_rate = history_series.smpRate or self.node.FrcsSmpRate
        target_category = self.node._day_category(fake_now.date())
        reference_start, matches_target = self.node._find_reference_day(
            history_series,
            history_map,
            forecast_start,
            fake_now.date(),
            target_category,
            sample_rate,
        )
        self.assertIsNotNone(reference_start)
        assert reference_start is not None

        forecast_series = self.node.DamPrcFrcs[self.zone]
        expected_values = self._expected_reference_blocks(
            start_time,
            values,
            forecast_series.t,
            [date(2024, 4, 21), date(2024, 4, 24)],
        )
        self.assertListEqual(forecast_series.val, expected_values)
        expected_validity = (
            ValidityKind_2025a.good if matches_target else ValidityKind_2025a.questionable
        )
        self.assertTrue(
            all(quality.validity in {expected_validity, ValidityKind_2025a.questionable} for quality in forecast_series.q)
        )

        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_fallback_to_previous_day_when_same_type_unavailable(self) -> None:
        fake_now = datetime(2024, 3, 4, 6, 45, tzinfo=timezone.utc)  # Monday

        start_time = datetime(2024, 3, 2, 0, 0, tzinfo=timezone.utc)
        values = self._populate_tes_series(start_time, days=2)  # Saturday and Sunday only

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        self._assert_forecast_matches_reference_blocks(
            fake_now,
            start_time,
            values,
            [date(2024, 3, 3), date(2024, 3, 3)],
        )

        forecast_series = self.node.DamPrcFrcs[self.zone]
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.questionable for quality in forecast_series.q)
        )

    def test_empty_history_produces_none_forecast_with_invalid_quality(self) -> None:
        fake_now = datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.DamPrcFrcs[self.zone]
        self.assertEqual(forecast_series.t, forecast_start)
        self.assertEqual(forecast_series.smpRate, self.node.FrcsSmpRate)
        self.assertEqual(forecast_series.smpNum, self.node.FrcsSmpNum)
        self.assertEqual(len(forecast_series.val), self.node.FrcsSmpNum)
        self.assertTrue(all(value is None for value in forecast_series.val))
        self.assertEqual(len(forecast_series.q), self.node.FrcsSmpNum)
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.invalid for quality in forecast_series.q)
        )

    def test_missing_quarter_hour_interpolated_with_questionable_quality(self) -> None:
        fake_now = datetime(2024, 3, 11, 8, 30, tzinfo=timezone.utc)  # Monday

        start_time = datetime(2024, 3, 4, 0, 0, tzinfo=timezone.utc)
        original_values = list(self._populate_tes_series(start_time, days=7))

        history_series = self.node.DamPrcTes[self.zone]
        history_map, _ = self.node._build_history(history_series)
        sample_rate = history_series.smpRate or self.node.FrcsSmpRate
        target_category = self.node._day_category(fake_now.date())
        reference_start, matches_target = self.node._find_reference_day(
            history_series,
            history_map,
            self.node._next_quarter_hour(fake_now),
            fake_now.date(),
            target_category,
            sample_rate,
        )
        self.assertIsNotNone(reference_start)
        assert reference_start is not None
        self.assertTrue(matches_target)

        missing_offset = int((reference_start - start_time) / self.sample_rate) + 10
        history_series.val[missing_offset] = None

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.DamPrcFrcs[self.zone]
        missing_step = 10
        expected_value = (original_values[missing_offset - 1] + original_values[missing_offset + 1]) / 2
        self.assertAlmostEqual(forecast_series.val[missing_step], expected_value)
        self.assertEqual(
            forecast_series.q[missing_step].validity,
            ValidityKind_2025a.questionable,
        )
        for index, quality in enumerate(forecast_series.q):
            if index == missing_step:
                continue
            self.assertEqual(quality.validity, ValidityKind_2025a.good)

    def test_forecast_with_real_now_generates_series(self) -> None:
        real_now = datetime.now(timezone.utc)
        forecast_start = self.node._next_quarter_hour(real_now)
        history_start_date = forecast_start.date() - timedelta(days=14)
        start_time = datetime(
            history_start_date.year,
            history_start_date.month,
            history_start_date.day,
            tzinfo=timezone.utc,
        )
        values = self._populate_tes_series(start_time, days=14)

        self.node()

        forecast_series = self.node.DamPrcFrcs[self.zone]
        actual_forecast_start = forecast_series.t
        self.assertIsNotNone(actual_forecast_start)

        assert actual_forecast_start is not None

        history_series = self.node.DamPrcTes[self.zone]
        history_map, _ = self.node._build_history(history_series)
        sample_rate = history_series.smpRate or self.node.FrcsSmpRate
        day_category = self.node._day_category(actual_forecast_start.date())
        reference_start, matches_target = self.node._find_reference_day(
            history_series,
            history_map,
            actual_forecast_start,
            actual_forecast_start.date(),
            day_category,
            sample_rate,
        )
        self.assertIsNotNone(reference_start)
        assert reference_start is not None

        reference_day = reference_start.date()
        self.assertEqual(forecast_series.t, actual_forecast_start)
        self.assertEqual(forecast_series.smpRate, self.node.FrcsSmpRate)
        self.assertEqual(forecast_series.smpNum, self.node.FrcsSmpNum)

        reference_dates = self._reference_dates_for_forecast(actual_forecast_start)
        expected_values = self._expected_reference_blocks(
            start_time,
            values,
            actual_forecast_start,
            reference_dates,
        )

        self.assertEqual(len(forecast_series.val), self.node.FrcsSmpNum)
        self.assertListEqual(forecast_series.val, expected_values)
        self.assertTrue(
            all(
                quality.validity in {ValidityKind_2025a.good, ValidityKind_2025a.questionable}
                for quality in forecast_series.q
            )
        )

    def test_forecast_uses_future_tes_values_when_available(self) -> None:
        fake_now = datetime(2024, 3, 11, 6, 30, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        start_time = datetime(2024, 3, 4, 0, 0)
        values = self._populate_tes_series(start_time, days=8)

        aligned_forecast_start = forecast_start.replace(tzinfo=None)
        steps_until_forecast = int((aligned_forecast_start - start_time) / self.sample_rate)
        available_future_steps = 12
        cutoff = steps_until_forecast + available_future_steps
        series = self.node.DamPrcTes[self.zone]
        series.val = series.val[:cutoff]
        series.smpNum = len(series.val)

        with patch.object(FFRC_DAM_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.DamPrcFrcs[self.zone]
        start_index = steps_until_forecast
        expected_direct = values[start_index : start_index + available_future_steps]
        self.assertEqual(len(expected_direct), available_future_steps)

        self.assertListEqual(forecast_series.val[:available_future_steps], expected_direct)
        self.assertTrue(
            all(
                quality.validity == ValidityKind_2025a.good
                for quality in forecast_series.q[:available_future_steps]
            )
        )

        first_day_steps = self._steps_in_forecast_block(forecast_start, self.node.FrcsSmpNum)
        remaining_same_day_steps = first_day_steps - available_future_steps
        after_direct_start = forecast_start + available_future_steps * self.sample_rate
        next_day_start = forecast_start + first_day_steps * self.sample_rate

        expected_remaining_same_day = self._expected_reference_block(
            start_time,
            values,
            date(2024, 3, 8),
            after_direct_start,
            remaining_same_day_steps,
        )
        expected_next_day = self._expected_reference_block(
            start_time,
            values,
            date(2024, 3, 11),
            next_day_start,
            self.node.FrcsSmpNum - first_day_steps,
        )

        self.assertListEqual(
            forecast_series.val[available_future_steps:],
            expected_remaining_same_day + expected_next_day,
        )

    def _populate_tes_series(self, start_time: datetime, days: int) -> list[int]:
        values: list[int] = []
        for day in range(days):
            base = day * 1000
            for slot in range(self.quarters_per_day):
                values.append(base + slot)

        series = self.node.DamPrcTes[self.zone]
        series.t = start_time
        series.smpRate = self.sample_rate
        series.smpNum = len(values)
        series.val = values

        return values

    def _assert_forecast_matches_reference_blocks(
        self,
        fake_now: datetime,
        start_time: datetime,
        values: list[int],
        reference_dates: list[date],
    ) -> None:
        forecast_series = self.node.DamPrcFrcs[self.zone]
        forecast_start = self.node._next_quarter_hour(fake_now)

        self.assertEqual(forecast_series.t, forecast_start)
        self.assertEqual(forecast_series.smpRate, self.node.FrcsSmpRate)
        self.assertEqual(forecast_series.smpNum, self.node.FrcsSmpNum)

        expected_values = self._expected_reference_blocks(
            start_time,
            values,
            forecast_start,
            reference_dates,
        )

        self.assertEqual(len(forecast_series.val), self.node.FrcsSmpNum)
        self.assertListEqual(forecast_series.val, expected_values)

    def _expected_reference_blocks(
        self,
        start_time: datetime,
        values: list[int],
        forecast_start: datetime,
        reference_dates: list[date],
    ) -> list[int]:
        expected: list[int] = []
        current_start = forecast_start
        remaining = self.node.FrcsSmpNum

        for reference_date in reference_dates:
            if remaining <= 0:
                break

            block_steps = self._steps_in_forecast_block(current_start, remaining)
            expected.extend(
                self._expected_reference_block(
                    start_time,
                    values,
                    reference_date,
                    current_start,
                    block_steps,
                )
            )
            remaining -= block_steps
            current_start += block_steps * self.sample_rate

        self.assertEqual(remaining, 0)
        return expected

    def _expected_reference_block(
        self,
        start_time: datetime,
        values: list[int],
        reference_date: date,
        block_start: datetime,
        block_steps: int,
    ) -> list[int]:
        day_index = (reference_date - start_time.date()).days
        midnight = datetime.combine(block_start.date(), time.min, tzinfo=block_start.tzinfo)
        offset = int((block_start - midnight) / self.sample_rate) % self.quarters_per_day
        start_idx = day_index * self.quarters_per_day + offset
        collected: list[int] = []
        fallback = values[-1] if values else 0
        for step in range(block_steps):
            idx = start_idx + step
            if 0 <= idx < len(values):
                collected.append(values[idx])
            else:
                collected.append(fallback)
        return collected

    def _steps_in_forecast_block(self, block_start: datetime, remaining: int) -> int:
        next_midnight = datetime.combine(
            block_start.date() + timedelta(days=1),
            time.min,
            tzinfo=block_start.tzinfo,
        )
        steps_until_midnight = max(0, int((next_midnight - block_start) / self.sample_rate))
        day_steps = steps_until_midnight if steps_until_midnight > 0 else self.quarters_per_day
        return min(remaining, day_steps)

    def _reference_dates_for_forecast(self, forecast_start: datetime) -> list[date]:
        history_series = self.node.DamPrcTes[self.zone]
        history_map, _ = self.node._build_history(history_series)
        sample_rate = history_series.smpRate or self.node.FrcsSmpRate
        reference_dates: list[date] = []
        current_start = forecast_start
        remaining = self.node.FrcsSmpNum

        while remaining > 0:
            block_steps = self._steps_in_forecast_block(current_start, remaining)
            target_category = self.node._day_category(current_start.date())
            reference_start, _ = self.node._find_reference_day(
                history_series,
                history_map,
                current_start,
                current_start.date(),
                target_category,
                sample_rate,
            )
            self.assertIsNotNone(reference_start)
            assert reference_start is not None
            reference_dates.append(reference_start.date())
            remaining -= block_steps
            current_start += block_steps * self.sample_rate

        return reference_dates


if __name__ == "__main__":
    unittest.main()
