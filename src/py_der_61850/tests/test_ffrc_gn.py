from datetime import datetime, timedelta, timezone
import math
import unittest
from unittest.mock import patch

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_GN_2025a import FFRC_GN_2025a
from py_der_61850.models.config_visitor import ConfigVisitor


class TestFFRCGNForecast(unittest.TestCase):
    def setUp(self) -> None:
        self.node = FFRC_GN_2025a(visitor=ConfigVisitor())
        self.node.FrcsSmpNum = 4 * 24
        self.user_id = "USR"
        self.sample_rate = self.node.FrcsSmpRate
        self.node.HorInsolTes[self.user_id] = TES_2025a()
        self.node.GnEnTotTes[self.user_id] = TES_2025a()

    def test_forecast_uses_future_samples_with_good_quality(self) -> None:
        fake_now = datetime(2024, 6, 1, 11, 7, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        start_time = forecast_start - timedelta(days=1)
        total_samples = self.node.FrcsSmpNum * 2
        values = list(range(total_samples))
        self._populate_series(start_time, values) # type: ignore

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.HorInsolFrcs[self.user_id]
        self.assertEqual(forecast_series.t, forecast_start)
        self.assertEqual(forecast_series.smpRate, self.node.FrcsSmpRate)
        self.assertEqual(forecast_series.smpNum, self.node.FrcsSmpNum)

        start_index = self.node.FrcsSmpNum
        end_index = start_index + self.node.FrcsSmpNum
        expected_values = values[start_index:end_index]
        actual_values = forecast_series.val[: len(expected_values)]
        self.assertListEqual(actual_values, expected_values)
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.good for quality in forecast_series.q[: len(expected_values)])
        )

    def test_forecast_repeats_latest_day_when_future_missing(self) -> None:
        fake_now = datetime(2024, 6, 1, 6, 30, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        start_time = forecast_start - timedelta(days=14)
        total_samples = self.node.FrcsSmpNum * 14
        values = list(range(total_samples))
        self._populate_series(start_time, values) # type: ignore

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.HorInsolFrcs[self.user_id]
        self.assertEqual(forecast_series.t, forecast_start)

        expected_values: list[int] = []
        for step in range(self.node.FrcsSmpNum):
            target_time = forecast_start + step * self.sample_rate
            reference_time = target_time - timedelta(days=1)
            index = int((reference_time - start_time) / self.sample_rate)
            expected_values.append(values[index])

        actual_values = forecast_series.val[: len(expected_values)]
        self.assertListEqual(actual_values, expected_values)
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.questionable for quality in forecast_series.q[: len(expected_values)])
        )

    def test_empty_history_generates_invalid_none_forecast(self) -> None:
        fake_now = datetime(2024, 6, 1, 8, 0, tzinfo=timezone.utc)
        self.node.HorInsolTes[self.user_id] = TES_2025a()

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.HorInsolFrcs[self.user_id]
        self.assertEqual(forecast_series.val, [None] * self.node.FrcsSmpNum)
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.invalid for quality in forecast_series.q)
        )

    def test_missing_future_sample_is_interpolated_with_questionable_quality(self) -> None:
        fake_now = datetime(2024, 6, 1, 10, 5, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        start_time = forecast_start - timedelta(days=1)
        total_samples = self.node.FrcsSmpNum * 2
        values = list(range(total_samples))
        gap_index = self.node.FrcsSmpNum + 10
        values[gap_index] = None # type: ignore
        self._populate_series(start_time, values) # type: ignore

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        forecast_series = self.node.HorInsolFrcs[self.user_id]
        missing_step = 10
        expected_value = (values[gap_index - 1] + values[gap_index + 1]) / 2
        self.assertLess(missing_step, len(forecast_series.val))
        self.assertAlmostEqual(forecast_series.val[missing_step], expected_value)
        self.assertEqual(
            forecast_series.q[missing_step].validity,
            ValidityKind_2025a.questionable,
        )

        for index, quality in enumerate(forecast_series.q[: len(forecast_series.val)]):
            if index == missing_step:
                continue
            self.assertEqual(quality.validity, ValidityKind_2025a.good)

    def test_generation_forecast_uses_linear_model(self) -> None:
        fake_now = datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        history_days = 365
        total_samples = self.node.FrcsSmpNum * history_days
        start_time = forecast_start - timedelta(days=history_days)

        irradiance_values: list[float] = []
        generation_values: list[float] = []
        slope = 0.3
        intercept = 40.0

        for index in range(total_samples):
            cycle_position = (index % self.node.FrcsSmpNum) / self.node.FrcsSmpNum
            irradiance = max(0.0, math.sin(math.pi * cycle_position)) * 900.0
            irradiance_values.append(irradiance)
            generation_values.append(intercept + slope * irradiance)

        self._populate_series(start_time, irradiance_values) # type: ignore
        self._populate_generation_series(start_time, generation_values) # type: ignore

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        insolation_forecast = self.node.HorInsolFrcs[self.user_id]
        generation_forecast = self.node.GnEnTotFrcs[self.user_id]

        self.assertEqual(generation_forecast.t, forecast_start)

        for insolation_value, generation_value, quality in zip(
            insolation_forecast.val, generation_forecast.val, generation_forecast.q
        ):
            if insolation_value is None:
                self.assertIsNone(generation_value)
                self.assertEqual(quality.validity, ValidityKind_2025a.invalid)
                continue

            numeric_insolation = float(insolation_value)
            expected_generation = (
                0.0
                if abs(numeric_insolation) <= 1e-6
                else max(0.0, intercept + slope * numeric_insolation)
            )
            self.assertAlmostEqual(generation_value, expected_generation)
            self.assertEqual(quality.validity, ValidityKind_2025a.good)

    def test_generation_forecast_ignores_large_positive_outliers_in_training_history(self) -> None:
        fake_now = datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        history_days = 120
        total_samples = self.node.FrcsSmpNum * history_days
        start_time = forecast_start - timedelta(days=history_days)

        irradiance_values: list[float] = []
        generation_values: list[float] = []
        slope = 0.3

        for index in range(total_samples):
            cycle_position = (index % self.node.FrcsSmpNum) / self.node.FrcsSmpNum
            irradiance = max(0.0, math.sin(math.pi * cycle_position)) * 900.0
            irradiance_values.append(irradiance)
            generation_values.append(slope * irradiance)

        outlier_index = self.node.FrcsSmpNum * 10 + self.node.FrcsSmpNum // 2
        generation_values[outlier_index] = 1_500_000.0

        self._populate_series(start_time, irradiance_values) # type: ignore
        self._populate_generation_series(start_time, generation_values) # type: ignore

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        insolation_forecast = self.node.HorInsolFrcs[self.user_id]
        generation_forecast = self.node.GnEnTotFrcs[self.user_id]

        self.assertEqual(generation_forecast.t, forecast_start)

        for insolation_value, generation_value, quality in zip(
            insolation_forecast.val, generation_forecast.val, generation_forecast.q
        ):
            if insolation_value is None:
                self.assertIsNone(generation_value)
                self.assertEqual(quality.validity, ValidityKind_2025a.invalid)
                continue

            expected_generation = slope * float(insolation_value)
            self.assertAlmostEqual(generation_value, expected_generation, places=6)
            self.assertEqual(quality.validity, ValidityKind_2025a.good)

    def test_generation_training_filter_rejects_negative_and_large_daytime_outliers(self) -> None:
        start_time = datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc)
        samples = [
            (start_time + 0 * self.sample_rate, 100.0, 30.0),
            (start_time + 1 * self.sample_rate, 200.0, 60.0),
            (start_time + 2 * self.sample_rate, 300.0, 90.0),
            (start_time + 3 * self.sample_rate, 400.0, 120.0),
            (start_time + 4 * self.sample_rate, 500.0, 1_500_000.0),
            (start_time + 5 * self.sample_rate, 250.0, -10.0),
        ]

        filtered_samples, removed_timestamps = self.node._filter_generation_training_samples(samples)

        self.assertEqual(len(filtered_samples), 4)
        self.assertEqual(
            removed_timestamps,
            [start_time + 4 * self.sample_rate, start_time + 5 * self.sample_rate],
        )

    def test_generation_training_filter_rejects_low_daytime_ratio_outliers(self) -> None:
        start_time = datetime(2024, 7, 1, 8, 0, tzinfo=timezone.utc)
        samples: list[tuple[datetime, float, float]] = []
        for index in range(20):
            insolation = 200.0 + index * 10.0
            samples.append((start_time + index * self.sample_rate, insolation, insolation * 2.0))

        low_ratio_time = start_time + 20 * self.sample_rate
        samples.append((low_ratio_time, 500.0, 20.0))

        filtered_samples, removed_timestamps = self.node._filter_generation_training_samples(samples)

        self.assertNotIn(low_ratio_time, [timestamp for timestamp, _, _ in filtered_samples])
        self.assertIn(low_ratio_time, removed_timestamps)
        self.assertEqual(len(filtered_samples), 20)

    def test_generation_training_filter_keeps_low_generation_when_irradiance_is_low(self) -> None:
        start_time = datetime(2024, 7, 1, 8, 0, tzinfo=timezone.utc)
        samples: list[tuple[datetime, float, float]] = []
        for index in range(20):
            insolation = 200.0 + index * 10.0
            samples.append((start_time + index * self.sample_rate, insolation, insolation * 2.0))

        low_irradiance_time = start_time + 20 * self.sample_rate
        samples.append((low_irradiance_time, 50.0, 0.0))

        filtered_samples, removed_timestamps = self.node._filter_generation_training_samples(samples)

        self.assertIn((low_irradiance_time, 50.0, 0.0), filtered_samples)
        self.assertNotIn(low_irradiance_time, removed_timestamps)

    def test_generation_forecast_marks_extrapolation_questionable(self) -> None:
        fake_now = datetime(2024, 7, 2, 12, 0, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        history_days = 365
        start_time = forecast_start - timedelta(days=history_days + 1)
        history_samples = self.node.FrcsSmpNum * history_days
        future_samples = self.node.FrcsSmpNum

        slope = 0.25
        intercept = 30.0
        max_history_irradiance = 900.0
        future_peak_irradiance = 1100.0

        irradiance_values: list[float] = []
        generation_values: list[float] = []

        for index in range(history_samples):
            cycle_position = (index % self.node.FrcsSmpNum) / self.node.FrcsSmpNum
            irradiance = max(0.0, math.sin(math.pi * cycle_position)) * max_history_irradiance
            irradiance_values.append(irradiance)
            generation_values.append(intercept + slope * irradiance)

        for index in range(future_samples):
            cycle_position = (index % self.node.FrcsSmpNum) / self.node.FrcsSmpNum
            irradiance = max(0.0, math.sin(math.pi * cycle_position)) * future_peak_irradiance
            irradiance_values.append(irradiance)

        self._populate_series(start_time, irradiance_values) # type: ignore
        self._populate_generation_series(start_time, generation_values) # type: ignore

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        generation_forecast = self.node.GnEnTotFrcs[self.user_id]
        insolation_forecast = self.node.HorInsolFrcs[self.user_id]

        self.assertTrue(
            any(
                validity.validity == ValidityKind_2025a.questionable
                for validity in generation_forecast.q
            )
        )

        for insolation_value, quality in zip(insolation_forecast.val, generation_forecast.q):
            if insolation_value is None:
                self.assertEqual(quality.validity, ValidityKind_2025a.invalid)
                continue

            expected_validity = (
                ValidityKind_2025a.questionable
                if insolation_value > max_history_irradiance
                else ValidityKind_2025a.good
            )
            self.assertEqual(quality.validity, expected_validity)

    def test_generation_forecast_with_insufficient_history_is_invalid(self) -> None:
        fake_now = datetime(2024, 7, 3, 12, 0, tzinfo=timezone.utc)
        forecast_start = self.node._next_quarter_hour(fake_now)

        start_time = forecast_start - timedelta(days=2)
        total_samples = self.node.FrcsSmpNum * 2
        irradiance_values = [float(index) for index in range(total_samples)]
        generation_values = [100.0] + [None] * (total_samples - 1)

        self._populate_series(start_time, irradiance_values) # type: ignore
        self._populate_generation_series(start_time, generation_values)

        with patch.object(FFRC_GN_2025a, "_now", return_value=fake_now):
            self.node()

        generation_forecast = self.node.GnEnTotFrcs[self.user_id]

        self.assertEqual(generation_forecast.t, forecast_start)
        self.assertListEqual(generation_forecast.val, [None] * generation_forecast.smpNum)
        self.assertTrue(
            all(quality.validity == ValidityKind_2025a.invalid for quality in generation_forecast.q)
        )

    def _populate_series(
        self, start_time: datetime, values: list[float | int | None]
    ) -> None:
        series = self.node.HorInsolTes[self.user_id] = TES_2025a()
        series.t = start_time
        series.smpRate = self.sample_rate
        series.smpNum = len(values)
        series.val = list(values)

    def _populate_generation_series(
        self, start_time: datetime, values: list[float | int | None]
    ) -> None:
        series = self.node.GnEnTotTes[self.user_id] = TES_2025a()
        series.t = start_time
        series.smpRate = self.sample_rate
        series.smpNum = len(values)
        series.val = list(values)


if __name__ == "__main__":
    unittest.main()
