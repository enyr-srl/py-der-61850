"""Regression tests for the InfluxDB pull de-duplication and uniform-grid alignment.

Background: InfluxDB returns one series per tag-set, so a single field comes back split by its
``quality`` tag (a live ``good`` series plus, e.g., a stale ``questionable`` one). The old pull
loaded BOTH (duplicate timestamps) straight into the TES without de-duplicating or aligning to a
time grid, so ``val[i]`` no longer matched ``t + i * smpRate`` -> the forecaster read the wrong
calendar instants (flat/garbage load forecasts, and all-invalid when an outage gap was in window).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a
from py_der_61850.enyr_61850_2025a.logical_node.pull_lod_influx import PULL_LOD_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class TestCollapseDuplicateTimestamps(unittest.TestCase):
    def setUp(self) -> None:
        self.node = PULL_LOD_INFLUXDB(visitor=ConfigVisitor())
        self.t0 = datetime(2024, 3, 4, 8, 30, tzinfo=timezone.utc)

    def test_prefers_finite_value_over_none_at_same_timestamp(self) -> None:
        df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0, self.t0 + timedelta(minutes=15)],
                "value": [None, -10.0, -5.0],
                "quality": ["good", "questionable", "good"],
            }
        )
        collapsed = self.node._collapse_duplicate_timestamps(df)
        self.assertEqual(len(collapsed), 2)
        row = collapsed[collapsed["Datetime"] == self.t0].iloc[0]
        self.assertEqual(row["value"], -10.0)  # finite wins over None even if None was 'good'

    def test_prefers_good_quality_when_both_finite(self) -> None:
        df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0],
                "value": [-20.0, -10.0],
                "quality": ["questionable", "good"],
            }
        )
        collapsed = self.node._collapse_duplicate_timestamps(df)
        self.assertEqual(len(collapsed), 1)
        self.assertEqual(collapsed.iloc[0]["value"], -10.0)

    def test_is_noop_for_unique_single_series(self) -> None:
        df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15)],
                "value": [-10.0, -12.0],
            }
        )
        collapsed = self.node._collapse_duplicate_timestamps(df)
        self.assertEqual(list(collapsed["value"]), [-10.0, -12.0])


class TestReindexSamplesToGrid(unittest.TestCase):
    def setUp(self) -> None:
        self.node = PULL_LOD_INFLUXDB(visitor=ConfigVisitor())
        self.t0 = datetime(2024, 3, 4, 0, 0, tzinfo=timezone.utc)
        self.rate = timedelta(minutes=15)

    def test_duplicates_collapse_and_gaps_become_none(self) -> None:
        q = self.node._quality_for_sample
        datetimes = [self.t0, self.t0, self.t0 + self.rate, self.t0 + 3 * self.rate]
        values = [None, -10.0, -5.0, -3.0]
        qualities = [q(None), q(-10.0), q(-5.0), q(-3.0)]

        t_start, out_values, out_qualities = self.node._reindex_samples_to_grid(
            datetimes, values, qualities, self.rate
        )

        self.assertEqual(t_start, self.t0)
        # grid spans t0 .. t0+3*rate -> 4 slots; index 2 has no sample -> None
        self.assertEqual(out_values, [-10.0, -5.0, None, -3.0])
        self.assertEqual(out_qualities[0].validity, ValidityKind_2025a.good)
        self.assertEqual(out_qualities[2].validity, ValidityKind_2025a.invalid)


class TestFirstCallPullAlignment(unittest.TestCase):
    """End-to-end: a duplicated, gappy value series must yield a single uniform TES."""

    def setUp(self) -> None:
        self.node = PULL_LOD_INFLUXDB(visitor=ConfigVisitor(rec_config={"users": ["USR"]}))
        self.forecast_node = FFRC_LOD_2025a(visitor=ConfigVisitor())
        self.node.FrcsRefLOD.setSrcRef = self.forecast_node
        self.rate = self.forecast_node.TesSmpRate
        self.t0 = datetime(2024, 3, 4, 0, 0, tzinfo=timezone.utc)

    def _value_df(self) -> pd.DataFrame:
        # 4 timestamps, each duplicated as good+questionable; one grid slot (index 2) skipped.
        times = [self.t0, self.t0 + self.rate, self.t0 + 3 * self.rate]
        rows = []
        for i, t in enumerate(times):
            rows.append({"Datetime": t, "value": -(10.0 + i), "quality": "good"})
            rows.append({"Datetime": t, "value": None, "quality": "questionable"})
        return pd.DataFrame(rows)

    def test_first_call_produces_single_uniform_series(self) -> None:
        value_df = self._value_df()

        def fake_get_data(*_args, **kwargs):
            # presence query (has extras) -> empty so masking is skipped; else the value series
            if kwargs.get("extras"):
                return pd.DataFrame()
            return value_df

        with patch.object(PULL_LOD_INFLUXDB, "_get_data", side_effect=fake_get_data):
            self.node._first_call_pull_strategy("FrcsRefLOD.setSrcRef", "LodEnTotTes", "USR")

        tes = self.forecast_node.LodEnTotTes["USR"]
        self.assertEqual(tes.t, self.t0)
        self.assertEqual(tes.smpRate, self.rate)
        # grid t0 .. t0+3*rate -> 4 slots (NOT 6 from the duplicated rows)
        self.assertEqual(len(tes.val), 4)
        self.assertEqual(tes.val, [-10.0, -11.0, None, -12.0])


if __name__ == "__main__":
    unittest.main()
