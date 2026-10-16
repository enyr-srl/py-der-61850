from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import pandas as pd

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.logical_node.pull_gn_influx import PULL_GN_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class TestPullGnInfluxGapMask(unittest.TestCase):
    def setUp(self) -> None:
        self.node = PULL_GN_INFLUXDB(visitor=ConfigVisitor())
        self.t0 = datetime(2024, 3, 4, 8, 30, tzinfo=timezone.utc)

    def test_missing_raw_quarter_invalidates_gap_and_following_interval(self) -> None:
        value_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15), self.t0 + timedelta(minutes=30)],
                "value": [10.0, 0.0, 5.0],
            }
        )
        presence_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15), self.t0 + timedelta(minutes=30)],
                "value": [1, 0, 1],
            }
        )

        with patch.object(PULL_GN_INFLUXDB, "_get_data", return_value=presence_df):
            values, qualities = self.node._build_samples_from_dataframe(
                value_df,
                measurement="USR",
                field="USR_pv_MMTN1.SupWh.actVal",
                start="-1d",
                stop="now()",
            )

        self.assertEqual(values[0], 10.0)
        self.assertIsNone(values[1])
        self.assertIsNone(values[2])
        self.assertEqual(qualities[0].validity, ValidityKind_2025a.good)
        self.assertEqual(qualities[1].validity, ValidityKind_2025a.invalid)
        self.assertEqual(qualities[2].validity, ValidityKind_2025a.invalid)

    def test_missing_presence_query_keeps_existing_samples(self) -> None:
        value_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15)],
                "value": [10.0, 12.0],
            }
        )

        with patch.object(PULL_GN_INFLUXDB, "_get_data", return_value=pd.DataFrame()):
            values, qualities = self.node._build_samples_from_dataframe(
                value_df,
                measurement="USR",
                field="USR_pv_MMTN1.SupWh.actVal",
                start="-1d",
                stop="now()",
            )

        self.assertEqual(values, [10.0, 12.0])
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in qualities))


if __name__ == "__main__":
    unittest.main()
