from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import pandas as pd

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_GN_2025a import FFRC_GN_2025a
from py_der_61850.enyr_61850_2025a.logical_node.pull_horinsol_influx import PULL_HORINSOL_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class TestPullHorinsolInflux(unittest.TestCase):
    def setUp(self) -> None:
        self.visitor = ConfigVisitor(rec_config={"users": ["PODXX1"]})
        self.node = PULL_HORINSOL_INFLUXDB(visitor=self.visitor)
        self.ffrc = FFRC_GN_2025a(visitor=self.visitor)
        self.node.FrcsRefGN.setSrcRef = self.ffrc
        self.t0 = datetime(2024, 6, 1, 8, 0, tzinfo=timezone.utc)

    def test_call_aligns_unsorted_weather_samples_and_keeps_zero_valid(self) -> None:
        df = pd.DataFrame(
            {
                "Datetime": [
                    self.t0 + timedelta(minutes=30),
                    self.t0,
                    self.t0 + timedelta(minutes=15),
                ],
                "value": [30.0, 0.0, 15.0],
            }
        )

        with patch.object(PULL_HORINSOL_INFLUXDB, "_get_data", return_value=df):
            self.node()

        series = self.ffrc.HorInsolTes["PODXX1"]
        self.assertEqual(series.t, self.t0)
        self.assertEqual(series.smpRate, self.ffrc.FrcsSmpRate)
        self.assertEqual(series.smpNum, 3)
        self.assertEqual(series.val, [0.0, 15.0, 30.0])
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in series.q))

    def test_call_inserts_invalid_none_for_missing_weather_windows(self) -> None:
        df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=30)],
                "value": [0.0, 30.0],
            }
        )

        with patch.object(PULL_HORINSOL_INFLUXDB, "_get_data", return_value=df):
            self.node()

        series = self.ffrc.HorInsolTes["PODXX1"]
        self.assertEqual(series.val, [0.0, None, 30.0])
        self.assertEqual(series.q[0].validity, ValidityKind_2025a.good)
        self.assertEqual(series.q[1].validity, ValidityKind_2025a.invalid)
        self.assertEqual(series.q[2].validity, ValidityKind_2025a.good)

    def test_runtime_merge_keeps_chronological_grid_and_trims_oldest_samples(self) -> None:
        self.ffrc.TesSmpNum = 2
        self.ffrc.FrcsSmpNum = 2
        existing_series = self.ffrc.HorInsolTes["PODXX1"] = TES_2025a()
        existing_series.t = self.t0
        existing_series.smpRate = self.ffrc.FrcsSmpRate
        existing_series.smpNum = 3
        existing_series.val = [1.0, 2.0, 3.0]
        existing_series.q = []
        self.node._first_call = False

        df = pd.DataFrame(
            {
                "Datetime": [
                    self.t0 + timedelta(minutes=45),
                    self.t0 + timedelta(minutes=60),
                ],
                "value": [4.0, 5.0],
            }
        )

        with patch.object(PULL_HORINSOL_INFLUXDB, "_get_data", return_value=df):
            self.node()

        series = self.ffrc.HorInsolTes["PODXX1"]
        self.assertEqual(series.t, self.t0 + timedelta(minutes=15))
        self.assertEqual(series.smpNum, 4)
        self.assertEqual(series.val, [2.0, 3.0, 4.0, 5.0])


if __name__ == "__main__":
    unittest.main()
