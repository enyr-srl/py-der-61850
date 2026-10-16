from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import pandas as pd

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_GN_2025a import FFRC_GN_2025a
from py_der_61850.enyr_61850_2025a.logical_node.pull_gn_influx import PULL_GN_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class TestPullGnInflux(unittest.TestCase):
    def setUp(self) -> None:
        self.visitor = ConfigVisitor(rec_config={"users": ["PODXX1"]})
        self.node = PULL_GN_INFLUXDB(visitor=self.visitor)
        self.node.FrcsRefGN.setSrcRef = FFRC_GN_2025a(visitor=self.visitor)
        self.t0 = datetime(2024, 3, 4, 8, 30, tzinfo=timezone.utc)

    def test_initialization(self) -> None:
        self.assertEqual(self.node._base_field, "pv_MMTN1.SupWh.actVal")
        self.assertTrue(self.node._first_call)
        self.assertEqual(self.node.FrcsRefGN.setSrcRef.TesSmpNum, 4 * 24 * 30)

    def test_get_query_extras_builds_positive_quarter_hour_energy_pipeline(self) -> None:
        extras = self.node._get_query_extras()

        self.assertIn("aggregateWindow(every: 15m, fn: last)", extras)
        self.assertIn("difference()", extras)
        self.assertIn("timeShift(duration: -15m)", extras)
        self.assertTrue(any("if r._value < 0.0 then r._value * -1.0" in extra for extra in extras))

    def test_call_populates_generation_tes_from_influx_data(self) -> None:
        value_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15)],
                "value": [10.0, 12.0],
            }
        )
        presence_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15)],
                "value": [1, 1],
            }
        )

        with patch.object(PULL_GN_INFLUXDB, "_get_data", side_effect=[value_df, presence_df]):
            self.node()

        series = self.node.FrcsRefGN.setSrcRef.GnEnTotTes["PODXX1"]
        self.assertFalse(self.node._first_call)
        self.assertEqual(series.t, self.t0)
        self.assertEqual(series.val, [10.0, 12.0])
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in series.q))

    def test_max_samples_limits_runtime_series(self) -> None:
        series = self.node.FrcsRefGN.setSrcRef.GnEnTotTes["PODXX1"] = type(
            "Series",
            (),
            {
                "t": self.t0,
                "smpRate": timedelta(minutes=15),
                "smpNum": 2,
                "val": [1.0, 2.0],
                "q": [],
            },
        )()
        self.node.FrcsRefGN.setSrcRef.TesSmpNum = 2
        self.node._first_call = False
        self.node._last_update = self.t0 - timedelta(minutes=20)

        value_df = pd.DataFrame({"Datetime": [self.t0 + timedelta(minutes=30)], "value": [3.0]})
        presence_df = pd.DataFrame({"Datetime": [self.t0 + timedelta(minutes=30)], "value": [1]})

        with patch("py_der_61850.enyr_61850_2025a.logical_node.pull_gn_influx.datetime") as datetime_mock:
            datetime_mock.now.return_value = self.t0
            with patch.object(PULL_GN_INFLUXDB, "_get_data", side_effect=[value_df, presence_df]):
                self.node()

        self.assertLessEqual(len(series.val), self.node.FrcsRefGN.setSrcRef.TesSmpNum)
        self.assertEqual(series.val, [2.0, 3.0])
        self.assertEqual(series.t, self.t0 + timedelta(minutes=15))


if __name__ == "__main__":
    unittest.main()
