import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a
from py_der_61850.models.config_visitor import ConfigVisitor


class TestFFRCLODForecast(unittest.TestCase):
    def setUp(self) -> None:
        self.node = FFRC_LOD_2025a(visitor=ConfigVisitor())
        self.user_id = "USR"
        self.node.LodEnTotTes[self.user_id] = TES_2025a()
        self.sample_rate = self.node.TesSmpRate
        self.quarters_per_day = int(timedelta(days=1) / self.sample_rate)
        self.node.FrcsSmpNum = self.quarters_per_day

    def test_weekday_uses_previous_same_weekday(self) -> None:
        fake_now = datetime(2024, 3, 11, 8, 30, tzinfo=timezone.utc)  # Monday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=7)
        values = self._populate_series(start_time, days=7)

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = date(2024, 3, 4)  # Previous Monday
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_saturday_uses_previous_saturday(self) -> None:
        fake_now = datetime(2024, 3, 9, 10, 15, tzinfo=timezone.utc)  # Saturday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=7)
        values = self._populate_series(start_time, days=7)

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = date(2024, 3, 2)
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_sunday_uses_previous_sunday(self) -> None:
        fake_now = datetime(2024, 3, 10, 12, 0, tzinfo=timezone.utc)  # Sunday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=7)
        values = self._populate_series(start_time, days=7)

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = date(2024, 3, 3)
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_holiday_uses_previous_sunday_when_no_other_holiday(self) -> None:
        fake_now = datetime(2024, 4, 25, 7, 0, tzinfo=timezone.utc)  # Holiday Thursday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=7)
        values = self._populate_series(start_time, days=7)

        self.node.Holidays.update({date(2024, 4, 25)})

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = date(2024, 4, 21)  # Previous Sunday
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_holiday_prefers_previous_holiday_when_available(self) -> None:
        fake_now = datetime(2024, 4, 26, 9, 0, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=7)
        values = self._populate_series(start_time, days=7)

        self.node.Holidays.update({date(2024, 4, 26), date(2024, 4, 25)})

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = date(2024, 4, 25)
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_weekday_skips_holiday_same_weekday_and_uses_previous_week(self) -> None:
        fake_now = datetime(2024, 4, 15, 8, 30, tzinfo=timezone.utc)  # Monday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=14)
        values = self._populate_series(start_time, days=14)

        self.node.Holidays.update({date(2024, 4, 8)})

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = date(2024, 4, 1)  # Previous non-holiday Monday
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_fallback_to_previous_day_with_insufficient_history(self) -> None:
        fake_now = datetime(2024, 3, 4, 6, 40, tzinfo=timezone.utc)  # Monday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=2)
        values = self._populate_series(start_time, days=2)  # Only weekend data

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = (forecast_start - timedelta(days=1)).date()
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.questionable for quality in forecast_series.q))

    def test_empty_history_produces_none_forecast_with_invalid_quality(self) -> None:
        fake_now = datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertEqual(forecast_series.t, forecast_start)
        self.assertEqual(forecast_series.smpRate, self.node.FrcsSmpRate)
        self.assertEqual(forecast_series.smpNum, self.node.FrcsSmpNum)
        self.assertEqual(len(forecast_series.val), self.node.FrcsSmpNum)
        self.assertTrue(all(value is None for value in forecast_series.val))
        self.assertEqual(len(forecast_series.q), self.node.FrcsSmpNum)
        self.assertTrue(all(quality.validity == ValidityKind_2025a.invalid for quality in forecast_series.q))

    def test_sparse_history_without_reference_day_stays_finite_and_questionable(self) -> None:
        """Robustness: with usable (but sparse) history and no qualifying reference day the
        forecast must degrade to a shaped/questionable series, never collapse to all-invalid."""
        fake_now = datetime(2024, 3, 11, 8, 30, tzinfo=timezone.utc)  # Monday
        start_time = self.node._next_quarter_hour(fake_now) - timedelta(days=2)

        series = self.node.LodEnTotTes[self.user_id]
        total = 2 * self.quarters_per_day
        # A finite sample only every 12th quarter -> far below the 75% reference-coverage bar,
        # so no candidate day qualifies and the time-of-day fallback must take over.
        values = [(-100.0 - (index % 8)) if index % 12 == 0 else None for index in range(total)]
        series.t = start_time
        series.smpRate = self.sample_rate
        series.smpNum = total
        series.val = values

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertEqual(len(forecast_series.val), self.node.FrcsSmpNum)
        self.assertTrue(all(value is not None for value in forecast_series.val))
        self.assertFalse(any(q.validity == ValidityKind_2025a.invalid for q in forecast_series.q))

    def test_missing_quarter_hour_interpolated_with_questionable_quality(self) -> None:
        fake_now = datetime(2024, 3, 11, 8, 30, tzinfo=timezone.utc)  # Monday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=7)
        original_values = list(self._populate_series(start_time, days=7))

        history_series = self.node.LodEnTotTes[self.user_id]
        history_map, _ = self.node._build_history(history_series)
        sample_rate = history_series.smpRate or self.node.FrcsSmpRate
        target_category = self.node._day_category(forecast_start.date())
        reference_start, matches_target = self.node._find_reference_period(
            history_series,
            history_map,
            forecast_start,
            target_category,
            sample_rate,
        )
        self.assertIsNotNone(reference_start)
        assert reference_start is not None
        self.assertTrue(matches_target)
        base_offset = int((reference_start - start_time) / self.sample_rate)
        missing_offset = base_offset + 10
        history_series.val[missing_offset] = None

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
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

    def test_positive_and_extreme_negative_outliers_are_invalidated(self) -> None:
        start_time = datetime(2024, 3, 1, 0, 0, tzinfo=timezone.utc)
        series = self.node.LodEnTotTes[self.user_id]
        series.t = start_time
        series.smpRate = self.sample_rate
        series.smpNum = 6
        series.val = [-100.0, -110.0, -120.0, 25.0, -130.0, -1_500_000.0]

        self.node._sanitize_series_values(series, self.user_id)

        self.assertEqual(series.val[:3], [-100.0, -110.0, -120.0])
        self.assertIsNone(series.val[3])
        self.assertEqual(series.val[4], -130.0)
        self.assertIsNone(series.val[5])
        self.assertEqual(series.q[3].validity, ValidityKind_2025a.invalid)
        self.assertEqual(series.q[5].validity, ValidityKind_2025a.invalid)

    def test_positive_outlier_in_reference_day_is_replaced_by_previous_day_value(self) -> None:
        fake_now = datetime(2024, 3, 11, 8, 30, tzinfo=timezone.utc)  # Monday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=7)
        original_values = list(self._populate_series(start_time, days=7))

        history_series = self.node.LodEnTotTes[self.user_id]
        history_map, _ = self.node._build_history(history_series)
        sample_rate = history_series.smpRate or self.node.FrcsSmpRate
        target_category = self.node._day_category(forecast_start.date())
        reference_start, matches_target = self.node._find_reference_period(
            history_series,
            history_map,
            forecast_start,
            target_category,
            sample_rate,
        )
        self.assertIsNotNone(reference_start)
        assert reference_start is not None
        self.assertTrue(matches_target)

        base_offset = int((reference_start - start_time) / self.sample_rate)
        offending_offset = base_offset + 10
        history_series.val[offending_offset] = 25.0

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        expected_value = (original_values[offending_offset - 1] + original_values[offending_offset + 1]) / 2
        self.assertAlmostEqual(forecast_series.val[10], expected_value)
        self.assertEqual(
            forecast_series.q[10].validity,
            ValidityKind_2025a.questionable,
        )

    def test_reference_day_with_insufficient_coverage_falls_back_to_previous_weekday(self) -> None:
        fake_now = datetime(2024, 3, 11, 8, 30, tzinfo=timezone.utc)  # Monday
        forecast_start = self.node._next_quarter_hour(fake_now)
        start_time = forecast_start - timedelta(days=14)
        values = self._populate_series(start_time, days=14)

        history_series = self.node.LodEnTotTes[self.user_id]
        same_weekday_reference = datetime(2024, 3, 4, 8, 30, tzinfo=timezone.utc)
        base_offset = int((same_weekday_reference - start_time) / self.sample_rate)
        for offset in range(int(self.quarters_per_day * 0.3)):
            history_series.val[base_offset + offset] = None

        with patch.object(FFRC_LOD_2025a, "_now", return_value=fake_now):
            self.node()

        expected_reference = date(2024, 2, 26)  # Previous Monday with sufficient coverage
        self._assert_forecast_matches_reference(forecast_start, start_time, values, expected_reference)

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def test_forecast_with_real_now_generates_series(self) -> None:
        real_now = datetime.now(timezone.utc)
        forecast_start = self.node._next_quarter_hour(real_now)
        start_time = forecast_start - timedelta(days=7)
        values = self._populate_series(start_time, days=7)

        self.node()

        forecast_series = self.node.LodEnTotFrcs[self.user_id]
        actual_forecast_start = forecast_series.t
        self.assertIsNotNone(actual_forecast_start)

        assert actual_forecast_start is not None

        history_series = self.node.LodEnTotTes[self.user_id]
        history_map, _ = self.node._build_history(history_series)
        sample_rate = history_series.smpRate or self.node.FrcsSmpRate
        day_category = self.node._day_category(actual_forecast_start.date())
        reference_start, matches_target = self.node._find_reference_period(
            history_series,
            history_map,
            actual_forecast_start,
            day_category,
            sample_rate,
        )
        self.assertIsNotNone(reference_start)
        assert reference_start is not None

        self._assert_forecast_matches_reference(
            actual_forecast_start,
            start_time,
            values,
            reference_start.date(),
        )
        self.assertTrue(matches_target)
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q))

    def _populate_series(self, start_time: datetime, days: int) -> list[int]:
        series = self.node.LodEnTotTes[self.user_id]
        values: list[int] = []
        current_time = start_time

        for index in range(days * self.quarters_per_day):
            elapsed = current_time - start_time
            day_index = int(elapsed // timedelta(days=1))
            slot_index = int((elapsed % timedelta(days=1)) // self.sample_rate)
            values.append(-(day_index * 1000 + slot_index + 1))
            current_time += self.sample_rate

        series.t = start_time
        series.smpRate = self.sample_rate
        series.smpNum = len(values)
        series.val = values

        return values

    def _assert_forecast_matches_reference(
        self,
        forecast_start: datetime,
        start_time: datetime,
        values: list[int],
        expected_reference: date,
    ) -> None:
        forecast_series = self.node.LodEnTotFrcs[self.user_id]

        self.assertEqual(forecast_series.t, forecast_start)
        self.assertEqual(forecast_series.smpRate, self.node.FrcsSmpRate)
        self.assertEqual(forecast_series.smpNum, self.node.FrcsSmpNum)
        self.assertEqual(len(forecast_series.val), self.node.FrcsSmpNum)

        tzinfo = start_time.tzinfo or timezone.utc
        reference_start = datetime.combine(expected_reference, forecast_start.time(), tzinfo=tzinfo)
        base_offset = int((reference_start - start_time) // self.sample_rate)
        self.assertGreaterEqual(base_offset, 0)

        fallback_value = values[-1] if values else 0
        expected_values: list[int] = []
        for step in range(self.node.FrcsSmpNum):
            moment_offset = base_offset + step
            if 0 <= moment_offset < len(values):
                expected_values.append(values[moment_offset])
            else:
                expected_values.append(fallback_value)

        self.assertListEqual(forecast_series.val, expected_values)


if __name__ == "__main__":
    unittest.main()
