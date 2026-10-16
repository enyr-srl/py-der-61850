import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.BCR_2025a import BCR_2025a
from py_der_61850.enyr_61850_2025a.data_objects.MV_2025a import MV_2025a
from py_der_61850.enyr_61850_2025a.logical_node.DECP_2025a import DECP_2025a
from py_der_61850.enyr_61850_2025a.logical_node.MMTN_2025a import MMTN_2025a
from py_der_61850.enyr_61850_2025a.logical_node.virtual_load_MMTN1_solver import virtual_load_MMTN1_solver
from py_der_61850.models.config_visitor import ConfigVisitor


def _good_bcr(value: int, timestamp: datetime) -> BCR_2025a:
    counter = BCR_2025a()
    counter.actVal = value
    counter.t = timestamp
    counter.q.validity = ValidityKind_2025a.good
    return counter


def _ref(obj: object) -> SimpleNamespace:
    return SimpleNamespace(setSrcRef=obj)


class TestSignedMMTNConvention(unittest.TestCase):
    def setUp(self) -> None:
        self.visitor = ConfigVisitor()
        self.t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    def _build_virtual_solver_fixture(
        self,
        *,
        pv_sup: int = 5,
        bess_sup: int = 0,
        bess_dmd: int = -2,
        pod_dmd: int = -7,
        pod_sup: int = 0,
        include_pv: bool = True,
        include_bess: bool = True,
    ) -> tuple[
        virtual_load_MMTN1_solver,
        SimpleNamespace | None,
        SimpleNamespace | None,
        SimpleNamespace,
        SimpleNamespace,
    ]:
        solver = virtual_load_MMTN1_solver(visitor=self.visitor)

        pv_mmtn = (
            SimpleNamespace(
                SupWh=_good_bcr(pv_sup, self.t0),
                DmdWh=_good_bcr(0, self.t0),
            )
            if include_pv
            else None
        )
        bess_mmtn = (
            SimpleNamespace(
                SupWh=_good_bcr(bess_sup, self.t0 + timedelta(minutes=5)),
                DmdWh=_good_bcr(bess_dmd, self.t0 + timedelta(minutes=5)),
            )
            if include_bess
            else None
        )
        pod_mmtn = SimpleNamespace(
            SupWh=_good_bcr(pod_sup, self.t0 + timedelta(minutes=10)),
            DmdWh=_good_bcr(pod_dmd, self.t0 + timedelta(minutes=10)),
        )
        load_mmtn = SimpleNamespace(SupWh=BCR_2025a(), DmdWh=BCR_2025a())

        der = SimpleNamespace(
            InclLod=_ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(load_mmtn))))),
            InclGn=(
                _ref(
                    SimpleNamespace(
                        InclGn=_ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(pv_mmtn)))))
                    )
                )
                if pv_mmtn is not None
                else SimpleNamespace()
            ),
            InclSto=(
                _ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(bess_mmtn)))))
                if bess_mmtn is not None
                else SimpleNamespace()
            ),
            OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(pod_mmtn))),
        )
        solver.DERRef = SimpleNamespace(setSrcRef=der)
        return solver, pv_mmtn, bess_mmtn, pod_mmtn, load_mmtn

    def _user_config_with_pod_counters(self, *, include_sup: bool) -> dict:
        pod_dos = [
            {
                "id": "DmdWh",
                "type": "BCR_2025a",
                "das": [{"id": "actVal", "type": "int", "value": 0}],
            }
        ]
        if include_sup:
            pod_dos.append(
                {
                    "id": "SupWh",
                    "type": "BCR_2025a",
                    "das": [{"id": "actVal", "type": "int", "value": 0}],
                }
            )
        return {
            "id": "PODXX4",
            "devices": [
                {
                    "id": "pod",
                    "lns": [
                        {
                            "id": "MMTN1",
                            "type": "MMTN_2025a",
                            "dos": pod_dos,
                        }
                    ],
                }
            ],
        }

    def test_mmtn_accumulates_negative_daily_counter_and_handles_reset(self) -> None:
        node = MMTN_2025a(visitor=self.visitor)

        node.DmdWhDay.actVal = -10
        node.DmdWhDay.t = self.t0
        node.DmdWhDay.q.validity = ValidityKind_2025a.good
        node()
        self.assertEqual(node.DmdWh.actVal, -10)

        node.DmdWhDay.actVal = -20
        node.DmdWhDay.t = self.t0 + timedelta(minutes=15)
        node()
        self.assertEqual(node.DmdWh.actVal, -20)

        node.DmdWhDay.actVal = -5
        node.DmdWhDay.t = self.t0 + timedelta(days=1)
        node()
        self.assertEqual(node.DmdWh.actVal, -25)

    def test_mmtn_bootstrap_recovers_same_day_delta(self) -> None:
        node = MMTN_2025a(visitor=self.visitor)

        node.bootstrap_total_from_history(
            "DmdWh",
            total_value=-100,
            total_timestamp=self.t0,
            previous_daily_value=-40,
        )
        node.DmdWhDay.actVal = -55
        node.DmdWhDay.t = self.t0 + timedelta(minutes=15)
        node.DmdWhDay.q.validity = ValidityKind_2025a.good

        node()

        self.assertEqual(node.DmdWh.actVal, -115)
        self.assertEqual(node.DmdWh.q.validity, ValidityKind_2025a.good)

    def test_mmtn_bootstrap_cross_day_marks_total_as_questionable(self) -> None:
        node = MMTN_2025a(visitor=self.visitor)

        node.bootstrap_total_from_history(
            "DmdWh",
            total_value=-100,
            total_timestamp=self.t0,
            previous_daily_value=-90,
            mark_questionable=True,
        )
        node.DmdWhDay.actVal = -5
        node.DmdWhDay.t = self.t0 + timedelta(days=1)
        node.DmdWhDay.q.validity = ValidityKind_2025a.good

        node()

        self.assertEqual(node.DmdWh.actVal, -105)
        self.assertEqual(node.DmdWh.q.validity, ValidityKind_2025a.questionable)

    def test_mmtn_logs_sign_convention_warning_once_per_offending_value(self) -> None:
        node = MMTN_2025a(visitor=self.visitor)

        node.SupWh.actVal = 0
        node.SupWh.t = self.t0
        node.SupWh.q.validity = ValidityKind_2025a.good

        node.DmdWh.actVal = 3
        node.DmdWh.t = self.t0
        node.DmdWh.q.validity = ValidityKind_2025a.good

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.MMTN_2025a"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            node()

        joined_logs = "\n".join(captured.output)
        self.assertIn("SupWh.actVal", joined_logs)
        self.assertIn("DmdWh.actVal", joined_logs)

        with self.assertNoLogs(logger_name, level="WARNING"):
            node()

    def test_mmtn_logs_monotonicity_violations_for_sup_and_dmd(self) -> None:
        node = MMTN_2025a(visitor=self.visitor)
        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.MMTN_2025a"

        node.SupWh.actVal = 10
        node.SupWh.t = self.t0
        node.SupWh.q.validity = ValidityKind_2025a.good
        node.DmdWh.actVal = -10
        node.DmdWh.t = self.t0
        node.DmdWh.q.validity = ValidityKind_2025a.good
        node()

        node.SupWh.actVal = 8
        node.SupWh.t = self.t0 + timedelta(minutes=15)
        node.DmdWh.actVal = -8
        node.DmdWh.t = self.t0 + timedelta(minutes=15)

        with self.assertLogs(logger_name, level="WARNING") as captured:
            node()

        joined_logs = "\n".join(captured.output)
        self.assertIn("MMTN monotonicity violated for SupWh.actVal", joined_logs)
        self.assertIn("previous=10", joined_logs)
        self.assertIn("current=8", joined_logs)
        self.assertIn("expected non-decreasing behavior", joined_logs)
        self.assertIn("MMTN monotonicity violated for DmdWh.actVal", joined_logs)
        self.assertIn("previous=-10", joined_logs)
        self.assertIn("current=-8", joined_logs)
        self.assertIn("expected non-increasing behavior", joined_logs)

        with self.assertNoLogs(logger_name, level="WARNING"):
            node()

    def test_decp_integrates_negative_power_into_decreasing_demand_counter(self) -> None:
        node = DECP_2025a(visitor=self.visitor)

        watt = MV_2025a()
        watt.mag = -1000.0
        watt.t = self.t0
        watt.q.validity = ValidityKind_2025a.good

        energy = SimpleNamespace(SupWh=BCR_2025a(), DmdWh=BCR_2025a())
        mmxn_ref = SimpleNamespace(setSrcRef=SimpleNamespace(Watt=watt))
        mmtn_ref = SimpleNamespace(setSrcRef=energy)

        node._integrate_pair(mmxn_ref, mmtn_ref)
        self.assertEqual(energy.DmdWh.actVal, 0)

        watt.t = self.t0 + timedelta(hours=1)
        node._integrate_pair(mmxn_ref, mmtn_ref)
        self.assertEqual(energy.DmdWh.actVal, -1000)
        self.assertEqual(energy.DmdWh.q.validity, ValidityKind_2025a.good)

    def test_decp_accumulates_sub_wh_residuals_between_fast_samples(self) -> None:
        node = DECP_2025a(visitor=self.visitor)

        watt = MV_2025a()
        watt.mag = -1000.0
        watt.t = self.t0
        watt.q.validity = ValidityKind_2025a.good

        energy = SimpleNamespace(SupWh=BCR_2025a(), DmdWh=BCR_2025a())
        mmxn_ref = SimpleNamespace(setSrcRef=SimpleNamespace(Watt=watt))
        mmtn_ref = SimpleNamespace(setSrcRef=energy)

        node._integrate_pair(mmxn_ref, mmtn_ref)
        for step in range(1, 8):
            watt.t = self.t0 + timedelta(seconds=0.5 * step)
            node._integrate_pair(mmxn_ref, mmtn_ref)

        self.assertEqual(energy.DmdWh.actVal, 0)

        watt.t = self.t0 + timedelta(seconds=4)
        node._integrate_pair(mmxn_ref, mmtn_ref)
        self.assertEqual(energy.DmdWh.actVal, -1)
        self.assertIsInstance(energy.DmdWh.actVal, int)

    def test_decp_keeps_import_export_residuals_separate_on_sign_changes(self) -> None:
        node = DECP_2025a(visitor=self.visitor)

        watt = MV_2025a()
        watt.mag = -2000.0
        watt.t = self.t0
        watt.q.validity = ValidityKind_2025a.good

        energy = SimpleNamespace(SupWh=BCR_2025a(), DmdWh=BCR_2025a())
        mmxn_ref = SimpleNamespace(setSrcRef=SimpleNamespace(Watt=watt))
        mmtn_ref = SimpleNamespace(setSrcRef=energy)

        node._integrate_pair(mmxn_ref, mmtn_ref)

        watt.t = self.t0 + timedelta(seconds=2)
        node._integrate_pair(mmxn_ref, mmtn_ref)
        self.assertEqual(energy.DmdWh.actVal, -1)
        self.assertEqual(energy.SupWh.actVal, 0)

        watt.mag = 2000.0
        watt.t = self.t0 + timedelta(seconds=4)
        node._integrate_pair(mmxn_ref, mmtn_ref)
        self.assertEqual(energy.DmdWh.actVal, -1)
        self.assertEqual(energy.SupWh.actVal, 1)

        watt.mag = -2000.0
        watt.t = self.t0 + timedelta(seconds=6)
        node._integrate_pair(mmxn_ref, mmtn_ref)
        self.assertEqual(energy.DmdWh.actVal, -2)
        self.assertEqual(energy.SupWh.actVal, 1)

    def test_decp_validates_total_counter_after_fallback_update(self) -> None:
        node = DECP_2025a(visitor=self.visitor)
        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.MMTN_2025a"

        total_energy = MMTN_2025a(visitor=self.visitor)
        total_energy.DmdWh.actVal = -10
        total_energy.DmdWh.t = self.t0
        total_energy.DmdWh.q.validity = ValidityKind_2025a.good
        total_energy.validate_invariants()

        total_power = SimpleNamespace(Watt=MV_2025a())
        total_power.Watt.q.validity = ValidityKind_2025a.invalid
        branch_energy = SimpleNamespace(
            SupWh=_good_bcr(0, self.t0 + timedelta(minutes=5)),
            DmdWh=_good_bcr(-5, self.t0 + timedelta(minutes=5)),
        )

        node.ElcMsRef1 = _ref(total_power)
        node.ElcMsRef2 = _ref(total_energy)
        node.ElcMsRef4 = _ref(branch_energy)
        node.ElcMsRef6 = _ref(None)
        node.ElcMsRef8 = _ref(None)
        node.ElcMsRef10 = _ref(None)

        with self.assertLogs(logger_name, level="WARNING") as captured:
            node()

        self.assertEqual(total_energy.DmdWh.actVal, -5)
        joined_logs = "\n".join(captured.output)
        self.assertIn("MMTN monotonicity violated for DmdWh.actVal", joined_logs)

    def test_virtual_load_solver_respects_signed_demand_convention(self) -> None:
        solver, _pv_mmtn, _bess_mmtn, _pod_mmtn, load_mmtn = self._build_virtual_solver_fixture()

        solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, -10)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.good)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=10))

    def test_virtual_load_solver_validates_target_counter_after_write(self) -> None:
        solver = virtual_load_MMTN1_solver(visitor=self.visitor)
        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.MMTN_2025a"

        load_mmtn = MMTN_2025a(visitor=self.visitor)
        load_mmtn.DmdWh.actVal = -10
        load_mmtn.DmdWh.t = self.t0
        load_mmtn.DmdWh.q.validity = ValidityKind_2025a.good
        load_mmtn.validate_invariants()

        pv_mmtn = SimpleNamespace(
            SupWh=_good_bcr(4, self.t0 + timedelta(minutes=20)),
            DmdWh=_good_bcr(0, self.t0 + timedelta(minutes=20)),
        )
        bess_mmtn = SimpleNamespace(
            SupWh=_good_bcr(0, self.t0 + timedelta(minutes=20)),
            DmdWh=_good_bcr(-2, self.t0 + timedelta(minutes=20)),
        )
        pod_mmtn = SimpleNamespace(
            SupWh=_good_bcr(0, self.t0 + timedelta(minutes=20)),
            DmdWh=_good_bcr(-7, self.t0 + timedelta(minutes=20)),
        )

        der = SimpleNamespace(
            InclLod=_ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(load_mmtn))))),
            InclGn=_ref(
                SimpleNamespace(InclGn=_ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(pv_mmtn))))))
            ),
            InclSto=_ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(bess_mmtn))))),
            OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(pod_mmtn))),
        )
        solver.DERRef = SimpleNamespace(setSrcRef=der)

        with self.assertLogs(logger_name, level="WARNING") as captured:
            solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, -9)
        joined_logs = "\n".join(captured.output)
        self.assertIn("MMTN monotonicity violated for DmdWh.actVal", joined_logs)

    def test_virtual_load_solver_logs_offending_addend_when_load_increases(self) -> None:
        solver, pv_mmtn, _bess_mmtn, _pod_mmtn, load_mmtn = self._build_virtual_solver_fixture()

        solver()
        self.assertEqual(load_mmtn.DmdWh.actVal, -10)

        pv_mmtn.SupWh.actVal = 4
        pv_mmtn.SupWh.t = self.t0 + timedelta(minutes=20)

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.virtual_load_MMTN1_solver"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, -10)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.questionable)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=20))

        joined_logs = "\n".join(captured.output)
        self.assertIn("detected load DmdWh increase", joined_logs)
        self.assertIn("pv_sup:source_delta=-1,load_delta=1", joined_logs)
        self.assertIn("pv_sup:delta=-1 expected >= 0", joined_logs)
        self.assertIn("last_applied=-10", joined_logs)
        self.assertIn("applied=-10", joined_logs)
        self.assertIn("clamped small increase <= 50 Wh", joined_logs)

    def test_virtual_load_solver_logs_monotonicity_against_external_load_resets(self) -> None:
        solver, pv_mmtn, bess_mmtn, pod_mmtn, load_mmtn = self._build_virtual_solver_fixture()

        solver()
        self.assertEqual(load_mmtn.DmdWh.actVal, -10)

        load_mmtn.DmdWh.actVal = -5
        load_mmtn.DmdWh.t = self.t0 + timedelta(minutes=20)
        load_mmtn.DmdWh.q.validity = ValidityKind_2025a.good

        pv_mmtn.SupWh.t = self.t0 + timedelta(minutes=20)
        bess_mmtn.SupWh.t = self.t0 + timedelta(minutes=20)
        bess_mmtn.DmdWh.t = self.t0 + timedelta(minutes=20)
        pod_mmtn.SupWh.t = self.t0 + timedelta(minutes=20)
        pod_mmtn.DmdWh.actVal = -2
        pod_mmtn.DmdWh.t = self.t0 + timedelta(minutes=20)

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.virtual_load_MMTN1_solver"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, -10)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.questionable)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=20))

        joined_logs = "\n".join(captured.output)
        self.assertIn("detected load DmdWh increase", joined_logs)
        self.assertIn("last_applied=-10", joined_logs)
        self.assertIn("current=-5", joined_logs)
        self.assertIn("computed=-5", joined_logs)
        self.assertIn("applied=-10", joined_logs)
        self.assertIn("clamped small increase <= 50 Wh", joined_logs)

    def test_virtual_load_solver_clamps_positive_increase_up_to_50_wh(self) -> None:
        solver, _pv_mmtn, _bess_mmtn, pod_mmtn, load_mmtn = self._build_virtual_solver_fixture()

        solver()
        self.assertEqual(load_mmtn.DmdWh.actVal, -10)

        pod_mmtn.DmdWh.actVal = 43
        pod_mmtn.DmdWh.t = self.t0 + timedelta(minutes=20)

        solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, -10)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.questionable)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=20))

    def test_virtual_load_solver_applies_large_positive_increase_as_questionable(self) -> None:
        solver, _pv_mmtn, _bess_mmtn, pod_mmtn, load_mmtn = self._build_virtual_solver_fixture()

        solver()
        self.assertEqual(load_mmtn.DmdWh.actVal, -10)

        pod_mmtn.DmdWh.actVal = 44
        pod_mmtn.DmdWh.t = self.t0 + timedelta(minutes=20)

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.virtual_load_MMTN1_solver"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, 41)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.questionable)
        joined_logs = "\n".join(captured.output)
        self.assertIn("applied large increase as questionable", joined_logs)
        self.assertIn("applied=41", joined_logs)

    def test_virtual_load_solver_absorbs_large_counter_reset_and_stays_continuous(self) -> None:
        # Un salto positivo enorme (> soglia reset) e' un ri-base dei contatori sorgente
        # (es. riconnessione FusionSolar), non consumo: NON va applicato come spike, e i
        # cicli successivi devono proseguire dal livello corretto (niente congelamento).
        solver, _pv_mmtn, _bess_mmtn, pod_mmtn, load_mmtn = self._build_virtual_solver_fixture()

        solver()
        self.assertEqual(load_mmtn.DmdWh.actVal, -10)

        # computed = pod_dmd - 3; con pod_dmd=6000 -> computed=5997, salto +6007 (> 5000) = reset.
        pod_mmtn.DmdWh.actVal = 6000
        pod_mmtn.DmdWh.t = self.t0 + timedelta(minutes=20)

        logger_name = "py_der_61850.enyr_61850_2025a.logical_node.virtual_load_MMTN1_solver"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            solver()

        # baseline tenuta, reset assorbito nell'offset, slot marcato questionable
        self.assertEqual(load_mmtn.DmdWh.actVal, -10)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.questionable)
        self.assertIn("absorbed counter reset", "\n".join(captured.output))

        # Dopo il reset, un consumo normale di 10 Wh deve portare a -20 (prosegue, non si congela).
        pod_mmtn.DmdWh.actVal = 5990
        pod_mmtn.DmdWh.t = self.t0 + timedelta(minutes=30)
        solver()
        self.assertEqual(load_mmtn.DmdWh.actVal, -20)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.good)

    def test_virtual_load_solver_handles_consumer_only_without_pv_or_bess(self) -> None:
        solver, pv_mmtn, bess_mmtn, _pod_mmtn, load_mmtn = self._build_virtual_solver_fixture(
            include_pv=False,
            include_bess=False,
        )

        solver()

        self.assertIsNone(pv_mmtn)
        self.assertIsNone(bess_mmtn)
        self.assertEqual(load_mmtn.DmdWh.actVal, -7)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.good)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=10))

    def test_virtual_load_solver_ignores_pod_sup_not_declared_in_user_config(self) -> None:
        visitor = ConfigVisitor(user_config=self._user_config_with_pod_counters(include_sup=False))
        solver = virtual_load_MMTN1_solver(visitor=visitor)

        pod_mmtn = SimpleNamespace(
            SupWh=BCR_2025a(),
            DmdWh=_good_bcr(-7, self.t0 + timedelta(minutes=10)),
        )
        load_mmtn = SimpleNamespace(SupWh=BCR_2025a(), DmdWh=BCR_2025a())
        der = SimpleNamespace(
            InclLod=_ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(load_mmtn))))),
            InclGn=SimpleNamespace(),
            InclSto=SimpleNamespace(),
            OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(pod_mmtn))),
        )
        solver.DERRef = SimpleNamespace(setSrcRef=der)

        solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, -7)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.good)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=10))

    def test_virtual_load_solver_uses_declared_pod_sup_quality(self) -> None:
        visitor = ConfigVisitor(user_config=self._user_config_with_pod_counters(include_sup=True))
        solver = virtual_load_MMTN1_solver(visitor=visitor)

        pod_mmtn = SimpleNamespace(
            SupWh=BCR_2025a(),
            DmdWh=_good_bcr(-7, self.t0 + timedelta(minutes=10)),
        )
        load_mmtn = SimpleNamespace(SupWh=BCR_2025a(), DmdWh=BCR_2025a())
        der = SimpleNamespace(
            InclLod=_ref(SimpleNamespace(OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(load_mmtn))))),
            InclGn=SimpleNamespace(),
            InclSto=SimpleNamespace(),
            OutEcpRef=_ref(SimpleNamespace(ElcMsRef2=_ref(pod_mmtn))),
        )
        solver.DERRef = SimpleNamespace(setSrcRef=der)

        solver()

        self.assertEqual(load_mmtn.DmdWh.actVal, -7)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.invalid)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=10))

    def test_virtual_load_solver_handles_producer_without_bess(self) -> None:
        solver, pv_mmtn, bess_mmtn, _pod_mmtn, load_mmtn = self._build_virtual_solver_fixture(
            include_bess=False,
        )

        solver()

        self.assertIsNotNone(pv_mmtn)
        self.assertIsNone(bess_mmtn)
        self.assertEqual(load_mmtn.DmdWh.actVal, -12)
        self.assertEqual(load_mmtn.DmdWh.q.validity, ValidityKind_2025a.good)
        self.assertEqual(load_mmtn.DmdWh.t, self.t0 + timedelta(minutes=10))
