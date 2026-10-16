import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a
from py_der_61850.enyr_61850_2025a.logical_node.pull_lod_influx import PULL_LOD_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class TestPullLodInfluxGapMask(unittest.TestCase):
    def setUp(self) -> None:
        self.node = PULL_LOD_INFLUXDB(visitor=ConfigVisitor())
        self.t0 = datetime(2024, 3, 4, 8, 30, tzinfo=timezone.utc)

    def test_is_tes_degraded_flags_mostly_none_full_series(self) -> None:
        # Serie a regime ma per lo piu' non-finita (25% finita < 60%): auto-riparazione richiesta.
        tes = TES_2025a()
        n = PULL_LOD_INFLUXDB._MIN_SAMPLES_TO_JUDGE + 100
        tes.val = [(-10.0 if i % 4 == 0 else None) for i in range(n)]
        self.assertTrue(self.node._is_tes_degraded(tes))

    def test_is_tes_degraded_ok_for_healthy_full_series(self) -> None:
        tes = TES_2025a()
        n = PULL_LOD_INFLUXDB._MIN_SAMPLES_TO_JUDGE + 100
        tes.val = [-10.0 - i for i in range(n)]
        self.assertFalse(self.node._is_tes_degraded(tes))

    def test_is_tes_degraded_ignores_short_filling_series(self) -> None:
        # Serie ancora corta (in riempimento): non e' degradata, non forzare il re-bootstrap.
        tes = TES_2025a()
        tes.val = [None] * 10
        self.assertFalse(self.node._is_tes_degraded(tes))

    def test_missing_raw_quarter_invalidates_gap_and_following_interval(self) -> None:
        value_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15), self.t0 + timedelta(minutes=30)],
                "value": [-10.0, -0.0, -5.0],
            }
        )
        presence_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15), self.t0 + timedelta(minutes=30)],
                "value": [1, 0, 1],
            }
        )

        with patch.object(PULL_LOD_INFLUXDB, "_get_data", return_value=presence_df):
            values, qualities = self.node._build_samples_from_dataframe(
                value_df,
                measurement="USR",
                field="USR_load_MMTN1.DmdWh.actVal",
                start="-1d",
                stop="now()",
            )

        self.assertEqual(values[0], -10.0)
        self.assertIsNone(values[1])
        self.assertIsNone(values[2])
        self.assertEqual(qualities[0].validity, ValidityKind_2025a.good)
        self.assertEqual(qualities[1].validity, ValidityKind_2025a.invalid)
        self.assertEqual(qualities[2].validity, ValidityKind_2025a.invalid)

    def test_missing_presence_query_keeps_existing_samples(self) -> None:
        value_df = pd.DataFrame(
            {
                "Datetime": [self.t0, self.t0 + timedelta(minutes=15)],
                "value": [-10.0, -12.0],
            }
        )

        with patch.object(PULL_LOD_INFLUXDB, "_get_data", return_value=pd.DataFrame()):
            values, qualities = self.node._build_samples_from_dataframe(
                value_df,
                measurement="USR",
                field="USR_load_MMTN1.DmdWh.actVal",
                start="-1d",
                stop="now()",
            )

        self.assertEqual(values, [-10.0, -12.0])
        self.assertTrue(all(quality.validity == ValidityKind_2025a.good for quality in qualities))

    def test_refresh_backfills_user_missing_from_initial_history(self) -> None:
        visitor = ConfigVisitor(rec_config={"users": ["PODXX4", "PODXX5"]})
        node = PULL_LOD_INFLUXDB(visitor=visitor)
        forecast_node = FFRC_LOD_2025a(visitor=visitor)
        forecast_node.LodEnTotTes["PODXX4"] = TES_2025a()
        node.FrcsRefLOD.setSrcRef = forecast_node
        node._first_call = False
        node._last_update = datetime.now() - timedelta(minutes=20)

        first_call_users: list[str] = []
        ref_call_users: list[str] = []

        def record_first_call(_source_field: str, _target_field: str, user_id: str) -> None:
            first_call_users.append(user_id)

        def record_ref_call(_source_field: str, _target_field: str, user_id: str) -> None:
            ref_call_users.append(user_id)

        with (
            patch.object(node, "_first_call_pull_strategy", side_effect=record_first_call),
            patch.object(node, "_ref_call_pull_strategy", side_effect=record_ref_call),
        ):
            node()

        self.assertEqual(first_call_users, ["PODXX5"])
        self.assertEqual(ref_call_users, ["PODXX4"])


if __name__ == "__main__":
    unittest.main()
