from datetime import datetime, timezone

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import (
    ValidityKind_2025a,
)
from py_der_61850.enyr_61850_2025a.logical_node.DPMC_2025a import DPMC_2025a
from py_der_61850.enyr_61850_2025a.logical_node.DSTO_2025a import DSTO_2025a
from py_der_61850.enyr_61850_2025a.logical_node.DWFL_2025a import DWFL_2025a
from py_der_61850.models.config_visitor import ConfigVisitor


def _build_node() -> tuple[DPMC_2025a, DSTO_2025a, DWFL_2025a]:
    visitor = ConfigVisitor()
    dpmc = DPMC_2025a(visitor)
    dsto = DSTO_2025a(visitor)
    dwfl = DWFL_2025a(visitor)

    dpmc.DERRef.setSrcRef = dsto
    dpmc.FctRef1.setSrcRef = dwfl

    dsto.SocWh.mag = 5_000.0
    dsto.UseWh.setMag = 10_000.0
    dsto.UseWhMinPct.setMag = 10.0
    dsto.UseWhMaxPct.setMag = 90.0
    dsto.ChaWMax.setMag = -2_500.0
    dsto.DschWMax.setMag = 2_500.0

    dwfl.FolWRef.q.validity = ValidityKind_2025a.good
    return dpmc, dsto, dwfl


def test_dpmc_preserves_cloud_timestamp_on_final_discharge_setpoint() -> None:
    dpmc, dsto, _dwfl = _build_node()
    cloud_timestamp = datetime(2026, 4, 23, 6, 45, tzinfo=timezone.utc)

    dpmc.WSpt2.Operate(1_200.0)
    dpmc.WSpt2.q.validity = ValidityKind_2025a.good
    dpmc.WSpt2.t = cloud_timestamp

    dpmc()

    assert dsto.DschWSpt.mxVal == 1_200.0
    assert dsto.DschWSpt.q.validity == ValidityKind_2025a.good
    assert dsto.DschWSpt.t == cloud_timestamp
    assert dsto.ChaWSpt.q.validity == ValidityKind_2025a.invalid
    assert dsto.ChaWSpt.t == cloud_timestamp


def test_dpmc_uses_rule_based_timestamp_when_cloud_setpoint_is_questionable() -> None:
    dpmc, dsto, dwfl = _build_node()
    cloud_timestamp = datetime(2026, 4, 23, 6, 45, tzinfo=timezone.utc)
    rule_based_timestamp = datetime(2026, 4, 23, 6, 44, 20, tzinfo=timezone.utc)

    dpmc.WSpt2.Operate(-1_500.0)
    dpmc.WSpt2.q.validity = ValidityKind_2025a.questionable
    dpmc.WSpt2.t = cloud_timestamp

    dwfl.FolWRef.mag = -800.0
    dwfl.FolWRef.t = rule_based_timestamp

    dpmc()

    assert dsto.ChaWSpt.mxVal == -800.0
    assert dsto.ChaWSpt.q.validity == ValidityKind_2025a.good
    assert dsto.ChaWSpt.t == rule_based_timestamp
    assert dsto.DschWSpt.q.validity == ValidityKind_2025a.invalid
    assert dsto.DschWSpt.t == rule_based_timestamp
