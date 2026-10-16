from datetime import datetime, timedelta, timezone
import unittest

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.data_objects.BCR_2025a import BCR_2025a
from py_der_61850.enyr_61850_2025a.logical_node.MMTN_2025a import MMTN_2025a
from py_der_61850.models.config_visitor import ConfigVisitor
from py_der_61850.models.image_process import ImageProcess
from py_der_61850.models.user_schema import DataAttribute
from py_der_61850.services.influx_counter_bootstrap import bootstrap_influx_counters_once


def _data_attribute(*, store: bool, bootstrap: str | None = None) -> DataAttribute:
    return DataAttribute(id="actVal", type="int", value=0, store=store, bootstrap=bootstrap)


def _good_daily(value: int, timestamp: datetime) -> BCR_2025a:
    counter = BCR_2025a()
    counter.actVal = value
    counter.t = timestamp
    counter.q.validity = ValidityKind_2025a.good
    return counter


class StubReflectionService:
    def __init__(self, values: dict[str, object]):
        self._values = values

    def get_value(self, identifier: str) -> object | None:
        return self._values.get(identifier)


class StubInfluxClient:
    def __init__(self, samples: dict[object, dict | None]):
        self._samples = samples
        self.calls: list[dict] = []

    def get_last(self, *, field: str, quality: str | None = None, at_or_before=None, **_kwargs) -> dict | None:
        self.calls.append({"field": field, "quality": quality, "at_or_before": at_or_before})
        key = (field, quality, at_or_before)
        if key in self._samples:
            return self._samples[key]
        key = (field, quality)
        if key in self._samples:
            return self._samples[key]
        return self._samples.get(field)


class TestInfluxCounterBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(minutes=15)
        self.visitor = ConfigVisitor()

    def _build_image_process(self) -> ImageProcess:
        return ImageProcess(
            data_attributes={
                "PODXX2_bess_MMTN1.DmdWh.actVal": _data_attribute(store=True, bootstrap="influx"),
                "PODXX2_bess_MMTN1.DmdWhDay.actVal": _data_attribute(store=True),
            }
        )

    def _build_image_process_without_daily_store(self) -> ImageProcess:
        return ImageProcess(
            data_attributes={
                "PODXX2_bess_MMTN1.DmdWh.actVal": _data_attribute(store=True, bootstrap="influx"),
                "PODXX2_bess_MMTN1.DmdWhDay.actVal": _data_attribute(store=False),
            }
        )

    def test_bootstrap_recovers_same_day_delta(self) -> None:
        mmtn = MMTN_2025a(visitor=self.visitor)
        current_daily = _good_daily(-50, self.t1)
        mmtn.DmdWhDay = current_daily
        reflection_service = StubReflectionService(
            {
                "PODXX2_bess_MMTN1": mmtn,
                "PODXX2_bess_MMTN1.DmdWhDay": current_daily,
            }
        )
        influx_client = StubInfluxClient(
            {
                "PODXX2_bess_MMTN1.DmdWh.actVal": {"value": -100, "Datetime": self.t0},
                "PODXX2_bess_MMTN1.DmdWhDay.actVal": {"value": -40, "Datetime": self.t0},
            }
        )

        bootstrap_influx_counters_once(
            image_process=self._build_image_process(),
            reflection_service=reflection_service,  # type: ignore[arg-type]
            influx_client=influx_client,  # type: ignore[arg-type]
            bucket="mise",
            measurement="PODXX2",
        )
        mmtn()

        self.assertEqual(mmtn.DmdWh.actVal, -110)
        self.assertEqual(mmtn.DmdWh.q.validity, ValidityKind_2025a.good)

    def test_bootstrap_prefers_good_total_and_matching_daily_timestamp(self) -> None:
        mmtn = MMTN_2025a(visitor=self.visitor)
        current_daily = _good_daily(-3120, self.t1)
        mmtn.DmdWhDay = current_daily
        reflection_service = StubReflectionService(
            {
                "PODXX2_bess_MMTN1": mmtn,
                "PODXX2_bess_MMTN1.DmdWhDay": current_daily,
            }
        )
        questionable_time = self.t1
        influx_client = StubInfluxClient(
            {
                ("PODXX2_bess_MMTN1.DmdWh.actVal", "good"): {
                    "value": -56180,
                    "Datetime": self.t0,
                    "quality": "good",
                },
                "PODXX2_bess_MMTN1.DmdWh.actVal": {
                    "value": -55040,
                    "Datetime": questionable_time,
                    "quality": "questionable",
                },
                ("PODXX2_bess_MMTN1.DmdWhDay.actVal", "good", self.t0): {
                    "value": -3110,
                    "Datetime": self.t0,
                    "quality": "good",
                },
            }
        )

        bootstrap_influx_counters_once(
            image_process=self._build_image_process(),
            reflection_service=reflection_service,  # type: ignore[arg-type]
            influx_client=influx_client,  # type: ignore[arg-type]
            bucket="mise",
            measurement="PODXX2",
        )
        mmtn()

        self.assertEqual(mmtn.DmdWh.actVal, -56190)
        self.assertEqual(mmtn.DmdWh.q.validity, ValidityKind_2025a.good)
        self.assertIn(
            {
                "field": "PODXX2_bess_MMTN1.DmdWhDay.actVal",
                "quality": "good",
                "at_or_before": self.t0,
            },
            influx_client.calls,
        )

    def test_bootstrap_skips_missing_history_with_warning(self) -> None:
        image_process = self._build_image_process()
        mmtn = MMTN_2025a(visitor=self.visitor)
        current_daily = _good_daily(-50, self.t1)
        mmtn.DmdWhDay = current_daily
        reflection_service = StubReflectionService(
            {
                "PODXX2_bess_MMTN1": mmtn,
                "PODXX2_bess_MMTN1.DmdWhDay": current_daily,
            }
        )
        influx_client = StubInfluxClient(
            {
                "PODXX2_bess_MMTN1.DmdWh.actVal": None,
                "PODXX2_bess_MMTN1.DmdWhDay.actVal": {"value": -40, "Datetime": self.t0},
            }
        )

        logger_name = "py_der_61850.services.influx_counter_bootstrap"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            bootstrap_influx_counters_once(
                image_process=image_process,
                reflection_service=reflection_service,  # type: ignore[arg-type]
                influx_client=influx_client,  # type: ignore[arg-type]
                bucket="mise",
                measurement="PODXX2",
            )

        self.assertEqual(mmtn.DmdWh.actVal, 0)
        self.assertIn("no historical total found in Influx", "\n".join(captured.output))

    def test_bootstrap_crossing_midnight_marks_total_as_questionable(self) -> None:
        mmtn = MMTN_2025a(visitor=self.visitor)
        current_daily = _good_daily(-5, self.t1)
        mmtn.DmdWhDay = current_daily
        reflection_service = StubReflectionService(
            {
                "PODXX2_bess_MMTN1": mmtn,
                "PODXX2_bess_MMTN1.DmdWhDay": current_daily,
            }
        )
        influx_client = StubInfluxClient(
            {
                "PODXX2_bess_MMTN1.DmdWh.actVal": {"value": -100, "Datetime": self.t0},
                "PODXX2_bess_MMTN1.DmdWhDay.actVal": {"value": -90, "Datetime": self.t0},
            }
        )

        logger_name = "py_der_61850.services.influx_counter_bootstrap"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            bootstrap_influx_counters_once(
                image_process=self._build_image_process(),
                reflection_service=reflection_service,  # type: ignore[arg-type]
                influx_client=influx_client,  # type: ignore[arg-type]
                bucket="mise",
                measurement="PODXX2",
            )
        mmtn()

        self.assertEqual(mmtn.DmdWh.actVal, -105)
        self.assertEqual(mmtn.DmdWh.q.validity, ValidityKind_2025a.questionable)
        self.assertIn("best-effort recovery", "\n".join(captured.output))

    def test_bootstrap_restores_total_even_when_daily_store_is_disabled(self) -> None:
        mmtn = MMTN_2025a(visitor=self.visitor)
        current_daily = _good_daily(-50, self.t1)
        mmtn.DmdWhDay = current_daily
        reflection_service = StubReflectionService(
            {
                "PODXX2_bess_MMTN1": mmtn,
                "PODXX2_bess_MMTN1.DmdWhDay": current_daily,
            }
        )
        influx_client = StubInfluxClient(
            {
                "PODXX2_bess_MMTN1.DmdWh.actVal": {"value": -100, "Datetime": self.t0},
                "PODXX2_bess_MMTN1.DmdWhDay.actVal": None,
            }
        )

        logger_name = "py_der_61850.services.influx_counter_bootstrap"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            bootstrap_influx_counters_once(
                image_process=self._build_image_process_without_daily_store(),
                reflection_service=reflection_service,  # type: ignore[arg-type]
                influx_client=influx_client,  # type: ignore[arg-type]
                bucket="mise",
                measurement="PODXX2",
            )
        mmtn()

        self.assertEqual(mmtn.DmdWh.actVal, -100)
        self.assertEqual(mmtn.DmdWh.q.validity, ValidityKind_2025a.good)
        self.assertIn("store=false", "\n".join(captured.output))

    def test_bootstrap_restores_total_when_daily_history_is_missing(self) -> None:
        mmtn = MMTN_2025a(visitor=self.visitor)
        current_daily = _good_daily(-50, self.t1)
        mmtn.DmdWhDay = current_daily
        reflection_service = StubReflectionService(
            {
                "PODXX2_bess_MMTN1": mmtn,
                "PODXX2_bess_MMTN1.DmdWhDay": current_daily,
            }
        )
        influx_client = StubInfluxClient(
            {
                "PODXX2_bess_MMTN1.DmdWh.actVal": {"value": -100, "Datetime": self.t0},
                "PODXX2_bess_MMTN1.DmdWhDay.actVal": None,
            }
        )

        logger_name = "py_der_61850.services.influx_counter_bootstrap"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            bootstrap_influx_counters_once(
                image_process=self._build_image_process(),
                reflection_service=reflection_service,  # type: ignore[arg-type]
                influx_client=influx_client,  # type: ignore[arg-type]
                bucket="mise",
                measurement="PODXX2",
            )
        mmtn()

        self.assertEqual(mmtn.DmdWh.actVal, -100)
        self.assertEqual(mmtn.DmdWh.q.validity, ValidityKind_2025a.good)
        self.assertIn("no historical daily", "\n".join(captured.output))
