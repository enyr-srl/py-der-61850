from datetime import datetime, timedelta, timezone
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_GN_2025a import FFRC_GN_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a
from py_der_61850.models.config_visitor import ConfigVisitor

try:
    from py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a import (
        DPMC_ERAB_2025a,
        OptProb_CSC_SC_EA_mBESS,
        OptProb_SC_EA_1BESS,
    )
except ModuleNotFoundError:
    DPMC_ERAB_2025a = None
    OptProb_CSC_SC_EA_mBESS = None
    OptProb_SC_EA_1BESS = None

try:
    from pyomo.common.numeric_types import value
    from pyomo.opt import SolverStatus, TerminationCondition
except ModuleNotFoundError:
    value = None
    SolverStatus = None
    TerminationCondition = None

try:
    from py_der_61850.enyr_61850_2025a.logical_node.read_from_influxdb import PULL_FROM_INFLUXDB
except ModuleNotFoundError:
    PULL_FROM_INFLUXDB = None


class TestNonFiniteForecastHandling(unittest.TestCase):
    def setUp(self) -> None:
        self.visitor = ConfigVisitor()
        self.t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    @staticmethod
    def _good_quality_list(size: int) -> list[Quality_2025a]:
        return [Quality_2025a(0) for _ in range(size)]

    def _build_forecast(self, values: list[float]) -> TES_2025a:
        series = TES_2025a()
        series.t = self.t0
        series.smpRate = timedelta(minutes=15)
        series.smpNum = len(values)
        series.val = values
        series.q = self._good_quality_list(len(values))
        return series

    @staticmethod
    def _build_setpoint_ref() -> SimpleNamespace:
        return SimpleNamespace(
            WSpt2=SimpleNamespace(
                q=SimpleNamespace(validity=ValidityKind_2025a.good),
                Operate=Mock(),
            ),
            FctRef1=SimpleNamespace(
                setSrcRef=SimpleNamespace(
                    FolWTgt=SimpleNamespace(setMag=0.0),
                    WThr=SimpleNamespace(setMag=0.0),
                    WPct=SimpleNamespace(setMag=100.0),
                )
            ),
        )

    @staticmethod
    def _build_incl_der(
        *,
        user_id: str,
        zone_id: str = "ZONE",
        soc_wh: float = 5000.0,
        use_wh: float = 10000.0,
        use_wh_min_pct: float = 10.0,
        use_wh_max_pct: float = 90.0,
        cha_w_max: float = -3000.0,
        dsch_w_max: float = 3000.0,
        cha_efc_pct: float = 96.0,
        dsch_efc_pct: float = 96.0,
        dcsc_cntt_watt: float = 6000.0,
        dprc_cntt_watt: float = 6000.0,
        dcsc_vrbl_fee: float = 0.0001,
        dprc_vrbl_fee: float = 0.0001,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            setSrcRef=SimpleNamespace(
                InclSto=SimpleNamespace(
                    setSrcRef=SimpleNamespace(
                        SocWh=SimpleNamespace(mag=soc_wh),
                        UseWh=SimpleNamespace(setMag=use_wh),
                        UseWhMinPct=SimpleNamespace(setMag=use_wh_min_pct),
                        UseWhMaxPct=SimpleNamespace(setMag=use_wh_max_pct),
                        ChaWMax=SimpleNamespace(setMag=cha_w_max),
                        DschWMax=SimpleNamespace(setMag=dsch_w_max),
                        ChaEfcPct=SimpleNamespace(setMag=cha_efc_pct),
                        DschEfcPct=SimpleNamespace(setMag=dsch_efc_pct),
                    )
                ),
                OutEcpRef=SimpleNamespace(
                    setSrcRef=SimpleNamespace(
                        AreaEpsEcpId=SimpleNamespace(dataNs=user_id),
                        AreaEpsMrkZnId=SimpleNamespace(dataNs=zone_id),
                        CsmpCnttRef=SimpleNamespace(
                            setSrcRef=SimpleNamespace(
                                VrblFee=SimpleNamespace(setMag=dcsc_vrbl_fee),
                                PctGriLos=SimpleNamespace(setMag=0.0),
                                VATpct=SimpleNamespace(setMag=0.0),
                                CnttWatt=SimpleNamespace(setMag=dcsc_cntt_watt),
                            )
                        ),
                        PrdcCnttRef=SimpleNamespace(
                            setSrcRef=SimpleNamespace(
                                VrblFee=SimpleNamespace(setMag=dprc_vrbl_fee),
                                VATpct=SimpleNamespace(setMag=0.0),
                                CnttWatt=SimpleNamespace(setMag=dprc_cntt_watt),
                            )
                        ),
                    )
                ),
            )
        )

    @unittest.skipIf(PULL_FROM_INFLUXDB is None, "pandas not installed in test environment")
    def test_pull_normalizes_non_finite_values_and_quality(self) -> None:
        self.assertEqual(PULL_FROM_INFLUXDB._normalize_numeric_sample(12), 12.0)
        self.assertIsNone(PULL_FROM_INFLUXDB._normalize_numeric_sample(float("nan")))
        self.assertIsNone(PULL_FROM_INFLUXDB._normalize_numeric_sample(float("inf")))
        self.assertEqual(
            PULL_FROM_INFLUXDB._quality_for_sample(None).validity,
            ValidityKind_2025a.invalid,
        )

    def test_ffrc_lod_sanitizes_non_finite_samples_and_marks_quality_invalid(self) -> None:
        node = FFRC_LOD_2025a(visitor=self.visitor)
        series = TES_2025a()
        series.t = self.t0
        series.smpRate = timedelta(minutes=15)
        series.val = [-1.0, float("nan"), -3.0, float("inf")]
        series.q = [Quality_2025a(0) for _ in series.val]

        node._sanitize_series_values(series)
        history, fallback = node._build_history(series)

        self.assertEqual(series.val, [-1.0, None, -3.0, None])
        self.assertEqual(series.q[1].validity, ValidityKind_2025a.invalid)
        self.assertEqual(series.q[3].validity, ValidityKind_2025a.invalid)
        self.assertEqual(len(history), 2)
        self.assertEqual(fallback, -3.0)

    def test_ffrc_gn_sanitizes_non_finite_samples_and_marks_quality_invalid(self) -> None:
        node = FFRC_GN_2025a(visitor=self.visitor)
        series = TES_2025a()
        series.t = self.t0
        series.smpRate = timedelta(minutes=15)
        series.val = [100.0, float("nan"), 300.0]
        series.q = [Quality_2025a(0) for _ in series.val]

        node._sanitize_series_values(series)
        history, timestamps = node._build_history(series)

        self.assertEqual(series.val, [100.0, None, 300.0])
        self.assertEqual(series.q[1].validity, ValidityKind_2025a.invalid)
        self.assertEqual(len(history), 2)
        self.assertEqual(len(timestamps), 2)

    @unittest.skipIf(DPMC_ERAB_2025a is None, "pyomo not installed in test environment")
    def test_dpmc_rejects_non_finite_forecast_values(self) -> None:
        node = DPMC_ERAB_2025a(visitor=self.visitor)
        forecast = TES_2025a()
        forecast.val = [1.0, float("nan"), 3.0]
        forecast.q = [Quality_2025a(0) for _ in forecast.val]

        is_valid = node._check_forecast_validity(forecast, "Load forecast", "USR")

        self.assertFalse(is_valid)
        self.assertEqual(forecast.val, [1.0, None, 3.0])
        self.assertEqual(forecast.q[1].validity, ValidityKind_2025a.invalid)

    @unittest.skipIf(DPMC_ERAB_2025a is None, "pyomo not installed in test environment")
    def test_dpmc_skips_user_when_generation_forecast_has_invalid_samples(self) -> None:
        node = DPMC_ERAB_2025a(visitor=ConfigVisitor(rec_config={"users": ["USR"]}))

        user_id = "USR"
        zone_id = "ZONE"

        load_forecast = TES_2025a()
        load_forecast.smpNum = 2
        load_forecast.smpRate = timedelta(minutes=15)
        load_forecast.val = [-1.0, -2.0]
        load_forecast.q = [Quality_2025a(0), Quality_2025a(0)]

        generation_forecast = TES_2025a()
        generation_forecast.smpNum = 2
        generation_forecast.smpRate = timedelta(minutes=15)
        generation_forecast.val = [1.0, float("nan")]
        generation_forecast.q = [Quality_2025a(0), Quality_2025a(0)]

        dam_forecast = TES_2025a()
        dam_forecast.smpNum = 2
        dam_forecast.smpRate = timedelta(minutes=15)
        dam_forecast.val = [100.0, 110.0]
        dam_forecast.q = [Quality_2025a(0), Quality_2025a(0)]

        node.FrcsRefLOD = SimpleNamespace(setSrcRef=SimpleNamespace(LodEnTotFrcs={user_id: load_forecast}))
        node.FrcsRefGN = SimpleNamespace(setSrcRef=SimpleNamespace(GnEnTotFrcs={user_id: generation_forecast}))
        node.FrcsRefDAM = SimpleNamespace(setSrcRef=SimpleNamespace(DamPrcFrcs={zone_id: dam_forecast}))

        incl_der = SimpleNamespace(
            setSrcRef=SimpleNamespace(
                OutEcpRef=SimpleNamespace(
                    setSrcRef=SimpleNamespace(
                        AreaEpsEcpId=SimpleNamespace(dataNs=user_id),
                        AreaEpsMrkZnId=SimpleNamespace(dataNs=zone_id),
                    )
                )
            )
        )
        node.DERRef = SimpleNamespace(setSrcRef=SimpleNamespace(InclDER1=incl_der))

        which_logic = SimpleNamespace(dataNs="SC_EA_1BESS")
        which_control = SimpleNamespace(dataNs="HuaweiAPI")
        setattr(node, "WhichLogic1", which_logic)
        setattr(node, "WhichControl1", which_control)
        setattr(node, "BessDpmcRef1", SimpleNamespace(setSrcRef=self._build_setpoint_ref()))

        node.Scheduler_SC_EA_1BESS = Mock()

        node()

        node.Scheduler_SC_EA_1BESS.assert_not_called()
        self.assertEqual(
            node.BessDpmcRef1.setSrcRef.WSpt2.q.validity,
            ValidityKind_2025a.invalid,
        )
        node.BessDpmcRef1.setSrcRef.WSpt2.Operate.assert_not_called()

    @unittest.skipIf(DPMC_ERAB_2025a is None, "pyomo not installed in test environment")
    def test_dpmc_csc_downgrades_failed_precheck_user_to_passive_group(self) -> None:
        node = DPMC_ERAB_2025a(visitor=ConfigVisitor(rec_config={"users": ["USR1", "USR2"]}))

        zone_id = "ZONE"
        user_1 = "USR1"
        user_2 = "USR2"

        load_forecast_1 = self._build_forecast([-300.0, -300.0])
        load_forecast_2 = self._build_forecast([-120.0, -150.0])
        generation_forecast_1 = self._build_forecast([100.0, 100.0])
        generation_forecast_2 = self._build_forecast([50.0, 50.0])
        dam_forecast = self._build_forecast([100.0, 110.0])

        node.FrcsRefLOD = SimpleNamespace(
            setSrcRef=SimpleNamespace(LodEnTotFrcs={user_1: load_forecast_1, user_2: load_forecast_2})
        )
        node.FrcsRefGN = SimpleNamespace(
            setSrcRef=SimpleNamespace(GnEnTotFrcs={user_1: generation_forecast_1, user_2: generation_forecast_2})
        )
        node.FrcsRefDAM = SimpleNamespace(setSrcRef=SimpleNamespace(DamPrcFrcs={zone_id: dam_forecast}))

        incl_der_1 = self._build_incl_der(user_id=user_1, zone_id=zone_id, cha_w_max=1000.0)
        incl_der_2 = self._build_incl_der(user_id=user_2, zone_id=zone_id)
        node.DERRef = SimpleNamespace(
            setSrcRef=SimpleNamespace(
                InclDER1=incl_der_1,
                InclDER2=incl_der_2,
            )
        )

        setattr(node, "WhichLogic1", SimpleNamespace(dataNs="CSC_SC_EA_mBESS"))
        setattr(node, "WhichLogic2", SimpleNamespace(dataNs="CSC_SC_EA_mBESS"))
        setattr(node, "WhichControl1", SimpleNamespace(dataNs="HuaweiAPI"))
        setattr(node, "WhichControl2", SimpleNamespace(dataNs="HuaweiAPI"))
        setattr(node, "BessDpmcRef1", SimpleNamespace(setSrcRef=self._build_setpoint_ref()))
        setattr(node, "BessDpmcRef2", SimpleNamespace(setSrcRef=self._build_setpoint_ref()))

        node.Scheduler_CSC_SC_EA_mBESS = Mock()

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            node()

        joined_logs = "\n".join(captured.output)
        self.assertIn("moved from active to passive group", joined_logs)
        self.assertIn("ChaWMax=1000.0 is positive", joined_logs)

        node.Scheduler_CSC_SC_EA_mBESS.assert_called_once()
        scheduler_kwargs = node.Scheduler_CSC_SC_EA_mBESS.call_args.kwargs
        self.assertEqual(
            sorted(scheduler_kwargs["CSC_active_partecipants_data"].keys()),
            [2],
        )
        self.assertEqual(
            scheduler_kwargs["CSC_passive_partecipants_fed"].val,
            [0.0, 0.0],
        )
        self.assertEqual(
            scheduler_kwargs["CSC_passive_partecipants_withdrawn"].val,
            [-200.0, -200.0],
        )
        self.assertEqual(
            node.BessDpmcRef1.setSrcRef.WSpt2.q.validity,
            ValidityKind_2025a.invalid,
        )
        node.BessDpmcRef1.setSrcRef.WSpt2.Operate.assert_not_called()

    @unittest.skipIf(
        DPMC_ERAB_2025a is None or SolverStatus is None or TerminationCondition is None,
        "pyomo not installed in test environment",
    )
    def test_dpmc_scheduler_skips_value_reads_and_logs_causes_when_single_bess_is_infeasible(self) -> None:
        node = DPMC_ERAB_2025a(visitor=self.visitor)
        incl_der = self._build_incl_der(user_id="USR", soc_wh=9000.0)
        bess_ref = SimpleNamespace(setSrcRef=self._build_setpoint_ref())
        gn_forecast = self._build_forecast([1000.0, 1200.0])
        lod_forecast = self._build_forecast([500.0, -800.0])
        dam_forecast = self._build_forecast([100.0, 110.0])

        fake_results = SimpleNamespace(
            solver=SimpleNamespace(
                status=SolverStatus.warning,
                termination_condition=TerminationCondition.infeasible,
                message="mock infeasible",
            ),
            solution=[],
        )
        fake_solver = SimpleNamespace(options={}, solve=Mock(return_value=fake_results))

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a"
        with patch(
            "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a.SolverFactory",
            return_value=fake_solver,
        ):
            with self.assertLogs(logger_name, level="WARNING") as captured:
                node.Scheduler_SC_EA_1BESS(
                    InclDER=incl_der,
                    BessDpmcRef=bess_ref,
                    GnFrcst=gn_forecast,
                    LodFrcst=lod_forecast,
                    DamPrcFrcst=dam_forecast,
                )

        joined_logs = "\n".join(captured.output)
        self.assertIn("skipped before solve", joined_logs)
        self.assertIn("load forecast has positive samples", joined_logs)
        self.assertEqual(bess_ref.setSrcRef.WSpt2.q.validity, ValidityKind_2025a.invalid)
        bess_ref.setSrcRef.WSpt2.Operate.assert_not_called()
        fake_solver.solve.assert_not_called()

    @unittest.skipIf(
        DPMC_ERAB_2025a is None or SolverStatus is None or TerminationCondition is None,
        "pyomo not installed in test environment",
    )
    def test_dpmc_scheduler_skips_value_reads_and_logs_causes_when_csc_is_infeasible(self) -> None:
        node = DPMC_ERAB_2025a(visitor=self.visitor)
        user_data = {
            1: {
                "InclDER": self._build_incl_der(user_id="USR1", cha_w_max=1000.0),
                "BessDpmcRef": SimpleNamespace(setSrcRef=self._build_setpoint_ref()),
                "GnFrcst": self._build_forecast([500.0, 600.0]),
                "LodFrcst": self._build_forecast([-200.0, -300.0]),
                "DamPrcFrcst": self._build_forecast([100.0, 90.0]),
            }
        }
        passive_fed = self._build_forecast([0.0, 0.0])
        passive_withdrawn = self._build_forecast([0.0, 0.0])

        fake_results = SimpleNamespace(
            solver=SimpleNamespace(
                status=SolverStatus.warning,
                termination_condition=TerminationCondition.infeasible,
                message="mock infeasible",
            ),
            solution=[],
        )
        fake_solver = SimpleNamespace(options={}, solve=Mock(return_value=fake_results))

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a"
        with patch(
            "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a.SolverFactory",
            return_value=fake_solver,
        ):
            with self.assertLogs(logger_name, level="WARNING") as captured:
                node.Scheduler_CSC_SC_EA_mBESS(
                    CSC_active_partecipants_data=user_data,
                    CSC_passive_partecipants_fed=passive_fed,
                    CSC_passive_partecipants_withdrawn=passive_withdrawn,
                )

        joined_logs = "\n".join(captured.output)
        self.assertIn("skipped before solve", joined_logs)
        self.assertIn("ChaWMax=1000.0 is positive", joined_logs)
        self.assertEqual(
            user_data[1]["BessDpmcRef"].setSrcRef.WSpt2.q.validity,
            ValidityKind_2025a.invalid,
        )
        user_data[1]["BessDpmcRef"].setSrcRef.WSpt2.Operate.assert_not_called()
        fake_solver.solve.assert_not_called()

    @unittest.skipIf(
        DPMC_ERAB_2025a is None or SolverStatus is None or TerminationCondition is None,
        "pyomo not installed in test environment",
    )
    def test_dpmc_scheduler_logs_solver_infeasible_when_precheck_passes(self) -> None:
        node = DPMC_ERAB_2025a(visitor=self.visitor)
        incl_der = self._build_incl_der(user_id="USR")
        bess_ref = SimpleNamespace(setSrcRef=self._build_setpoint_ref())
        gn_forecast = self._build_forecast([1000.0, 1200.0])
        lod_forecast = self._build_forecast([-500.0, -800.0])
        dam_forecast = self._build_forecast([100.0, 110.0])

        fake_results = SimpleNamespace(
            solver=SimpleNamespace(
                status=SolverStatus.warning,
                termination_condition=TerminationCondition.infeasible,
                message="mock infeasible",
            ),
            solution=[],
        )
        fake_solver = SimpleNamespace(options={}, solve=Mock(return_value=fake_results))

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a"
        with patch(
            "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a.SolverFactory",
            return_value=fake_solver,
        ):
            with self.assertLogs(logger_name, level="WARNING") as captured:
                node.Scheduler_SC_EA_1BESS(
                    InclDER=incl_der,
                    BessDpmcRef=bess_ref,
                    GnFrcst=gn_forecast,
                    LodFrcst=lod_forecast,
                    DamPrcFrcst=dam_forecast,
                )

        joined_logs = "\n".join(captured.output)
        self.assertIn("returned no usable solution", joined_logs)
        self.assertIn("no obvious sign or parameter inconsistency was detected", joined_logs)
        self.assertEqual(bess_ref.setSrcRef.WSpt2.q.validity, ValidityKind_2025a.invalid)
        bess_ref.setSrcRef.WSpt2.Operate.assert_not_called()
        fake_solver.solve.assert_called_once()

    @unittest.skipIf(
        DPMC_ERAB_2025a is None or SolverStatus is None or TerminationCondition is None,
        "pyomo not installed in test environment",
    )
    def test_dpmc_precheck_converts_interval_energy_to_average_power_before_limit_checks(self) -> None:
        node = DPMC_ERAB_2025a(visitor=self.visitor)
        incl_der = self._build_incl_der(
            user_id="USR",
            dsch_w_max=0.0,
            dcsc_cntt_watt=3000.0,
            dprc_cntt_watt=3000.0,
        )
        bess_ref = SimpleNamespace(setSrcRef=self._build_setpoint_ref())
        gn_forecast = self._build_forecast([0.0, 0.0])
        lod_forecast = self._build_forecast([-1000.0, -1000.0])
        dam_forecast = self._build_forecast([100.0, 110.0])

        fake_solver = SimpleNamespace(options={}, solve=Mock())
        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a"
        with patch(
            "py_der_61850.enyr_61850_2025a.logical_node.DPMC_ERAB_2025a.SolverFactory",
            return_value=fake_solver,
        ):
            with self.assertLogs(logger_name, level="WARNING") as captured:
                node.Scheduler_SC_EA_1BESS(
                    InclDER=incl_der,
                    BessDpmcRef=bess_ref,
                    GnFrcst=gn_forecast,
                    LodFrcst=lod_forecast,
                    DamPrcFrcst=dam_forecast,
                )

        joined_logs = "\n".join(captured.output)
        self.assertIn("skipped before solve", joined_logs)
        self.assertIn("forecast/contract/battery limits are incompatible", joined_logs)
        self.assertEqual(bess_ref.setSrcRef.WSpt2.q.validity, ValidityKind_2025a.invalid)
        bess_ref.setSrcRef.WSpt2.Operate.assert_not_called()
        fake_solver.solve.assert_not_called()

    @unittest.skipIf(
        OptProb_SC_EA_1BESS is None or value is None,
        "pyomo not installed in test environment",
    )
    def test_single_bess_objective_treats_contract_fees_as_eur_per_wh(self) -> None:
        incl_der = self._build_incl_der(
            user_id="USR",
            dcsc_vrbl_fee=0.0001,
            dprc_vrbl_fee=0.0001,
        )
        gn_forecast = self._build_forecast([0.0, 0.0])
        lod_forecast = self._build_forecast([0.0, 0.0])
        dam_forecast = self._build_forecast([100.0, 100.0])
        model = OptProb_SC_EA_1BESS(
            GnFrcst=gn_forecast,
            DamPrcFrcst=dam_forecast,
            LodFrcst=lod_forecast,
            InclDER=incl_der,
            ActiveAlphaOneConstraintRule=False,
        )

        model.WWithdrawn[0].value = -4000.0
        model.WWithdrawn[1].value = 0.0
        model.WFed[0].value = 0.0
        model.WFed[1].value = 4000.0
        model.WCharge[0].value = 0.0
        model.WCharge[1].value = 0.0
        model.WDischarge[0].value = 0.0
        model.WDischarge[1].value = 0.0
        model.WVariationAbs[0].value = 0.0

        # 4 kW over 15 min -> 1000 Wh. DAM at 100 EUR/MWh equals 0.0001 EUR/Wh.
        # Withdrawal costs 0.1 EUR (DAM) + 0.1 EUR (contract fee); injection nets to 0 EUR.
        self.assertAlmostEqual(value(model.Objective.expr), 0.2, places=9)

    @unittest.skipIf(
        OptProb_CSC_SC_EA_mBESS is None or value is None,
        "pyomo not installed in test environment",
    )
    def test_csc_objective_treats_contract_fees_as_eur_per_wh(self) -> None:
        user_data = {
            1: {
                "InclDER": self._build_incl_der(
                    user_id="USR1",
                    dcsc_vrbl_fee=0.0001,
                    dprc_vrbl_fee=0.0001,
                ),
                "BessDpmcRef": SimpleNamespace(setSrcRef=self._build_setpoint_ref()),
                "GnFrcst": self._build_forecast([0.0, 0.0]),
                "LodFrcst": self._build_forecast([0.0, 0.0]),
                "DamPrcFrcst": self._build_forecast([100.0, 100.0]),
            }
        }
        passive_fed = self._build_forecast([0.0, 0.0])
        passive_withdrawn = self._build_forecast([0.0, 0.0])
        model = OptProb_CSC_SC_EA_mBESS(
            users_data=user_data,
            CSC_passive_partecipants_fed=passive_fed,
            CSC_passive_partecipants_withdrawn=passive_withdrawn,
            ActiveAlphaOneConstraintRule=False,
            IncentivePrice=0.00012,
        )

        model.WWithdrawn[1, 0].value = -4000.0
        model.WWithdrawn[1, 1].value = 0.0
        model.WFed[1, 0].value = 0.0
        model.WFed[1, 1].value = 4000.0
        model.WCharge[1, 0].value = 0.0
        model.WCharge[1, 1].value = 0.0
        model.WDischarge[1, 0].value = 0.0
        model.WDischarge[1, 1].value = 0.0
        model.WVariationAbs[1, 0].value = 0.0
        model.CSC_Volume[0].value = 0.0
        model.CSC_Volume[1].value = 0.0

        self.assertAlmostEqual(value(model.Objective.expr), 0.2, places=9)

    @unittest.skipIf(
        OptProb_CSC_SC_EA_mBESS is None or value is None,
        "pyomo not installed in test environment",
    )
    def test_csc_incentive_is_treated_as_eur_per_wh(self) -> None:
        user_data = {
            1: {
                "InclDER": self._build_incl_der(user_id="USR1"),
                "BessDpmcRef": SimpleNamespace(setSrcRef=self._build_setpoint_ref()),
                "GnFrcst": self._build_forecast([0.0, 0.0]),
                "LodFrcst": self._build_forecast([0.0, 0.0]),
                "DamPrcFrcst": self._build_forecast([0.0, 0.0]),
            }
        }
        passive_fed = self._build_forecast([0.0, 0.0])
        passive_withdrawn = self._build_forecast([0.0, 0.0])
        model = OptProb_CSC_SC_EA_mBESS(
            users_data=user_data,
            CSC_passive_partecipants_fed=passive_fed,
            CSC_passive_partecipants_withdrawn=passive_withdrawn,
            ActiveAlphaOneConstraintRule=False,
            IncentivePrice=0.00012,
        )

        model.WWithdrawn[1, 0].value = 0.0
        model.WWithdrawn[1, 1].value = 0.0
        model.WFed[1, 0].value = 0.0
        model.WFed[1, 1].value = 0.0
        model.WCharge[1, 0].value = 0.0
        model.WCharge[1, 1].value = 0.0
        model.WDischarge[1, 0].value = 0.0
        model.WDischarge[1, 1].value = 0.0
        model.WVariationAbs[1, 0].value = 0.0
        model.CSC_Volume[0].value = 4000.0
        model.CSC_Volume[1].value = 0.0

        # 4 kW of CSC volume over 15 min -> 1000 Wh. At 0.00012 EUR/Wh the incentive is 0.12 EUR.
        self.assertAlmostEqual(value(model.Objective.expr), -0.12, places=9)
