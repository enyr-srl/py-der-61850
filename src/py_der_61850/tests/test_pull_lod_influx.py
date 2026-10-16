import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a
from py_der_61850.enyr_61850_2025a.logical_node.pull_lod_influx import PULL_LOD_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor

USERS = ["USR1", "USR2"]


class TestPullLodInflux(unittest.TestCase):
    """Unit tests for PULL_LOD_INFLUXDB pull scheduling, without InfluxDB access."""

    def setUp(self) -> None:
        visitor = ConfigVisitor(rec_config={"users": USERS})
        self.node = PULL_LOD_INFLUXDB(visitor=visitor)
        self.node.FrcsRefLOD.setSrcRef = FFRC_LOD_2025a(visitor=visitor)
        self.forecast = self.node.FrcsRefLOD.setSrcRef

        first_patch = patch.object(PULL_LOD_INFLUXDB, "_first_call_pull_strategy")
        ref_patch = patch.object(PULL_LOD_INFLUXDB, "_ref_call_pull_strategy")
        self.first_pull = first_patch.start()
        self.ref_pull = ref_patch.start()
        self.addCleanup(first_patch.stop)
        self.addCleanup(ref_patch.stop)

    def _pulled_users(self, mock) -> list[str]:
        return [call.args[2] for call in mock.call_args_list]

    def test_initialization(self) -> None:
        self.assertTrue(self.node._first_call)
        self.assertEqual(self.forecast.TesSmpNum, 7 * 24 * 4)

    def test_first_call_bootstraps_every_user(self) -> None:
        self.node()

        self.assertEqual(self._pulled_users(self.first_pull), USERS)
        self.ref_pull.assert_not_called()
        self.assertFalse(self.node._first_call)

    def test_call_within_sample_rate_does_not_pull_again(self) -> None:
        self.node()
        for user_id in USERS:
            self.forecast.LodEnTotTes[user_id] = TES_2025a()
        self.first_pull.reset_mock()

        self.node()

        self.first_pull.assert_not_called()
        self.ref_pull.assert_not_called()

    def test_call_within_sample_rate_bootstraps_only_missing_users(self) -> None:
        self.node()
        self.forecast.LodEnTotTes["USR1"] = TES_2025a()
        self.first_pull.reset_mock()

        self.node()

        self.assertEqual(self._pulled_users(self.first_pull), ["USR2"])
        self.ref_pull.assert_not_called()

    def test_call_after_sample_rate_appends_incrementally(self) -> None:
        self.node()
        for user_id in USERS:
            self.forecast.LodEnTotTes[user_id] = TES_2025a()
        self.first_pull.reset_mock()
        self.node._last_update = datetime.now() - self.forecast.TesSmpRate - timedelta(seconds=1)

        self.node()

        self.first_pull.assert_not_called()
        self.assertEqual(self._pulled_users(self.ref_pull), USERS)

    def test_periodic_rebootstrap(self) -> None:
        self.node()
        for user_id in USERS:
            self.forecast.LodEnTotTes[user_id] = TES_2025a()
        self.first_pull.reset_mock()
        self.node._last_update = datetime.now() - self.forecast.TesSmpRate - timedelta(seconds=1)
        self.node._cycles_since_bootstrap = PULL_LOD_INFLUXDB._REBOOTSTRAP_EVERY_CYCLES

        self.node()

        self.assertEqual(self._pulled_users(self.first_pull), USERS)
        self.ref_pull.assert_not_called()
        self.assertEqual(self.node._cycles_since_bootstrap, 0)


if __name__ == "__main__":
    unittest.main()
