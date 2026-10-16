from datetime import date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from py_der_61850.enyr_61850_2025a.logical_node.FFRC_DAM_2025a import FFRC_DAM_2025a
from py_der_61850.enyr_61850_2025a.logical_node.pull_dam_ftp import (
    DamRefreshStatus,
    PULL_DAM_FTP,
    ROME_TZ,
)
from py_der_61850.models.config_visitor import ConfigVisitor


def _user_config(zone: str) -> dict:
    return {
        "devices": [
            {
                "lns": [
                    {
                        "type": "DPCC_2025a",
                        "dos": [
                            {
                                "id": "AreaEpsMrkZnId",
                                "das": [
                                    {
                                        "id": "dataNs",
                                        "value": zone,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }


def _build_visitor() -> ConfigVisitor:
    return ConfigVisitor(users_config=[_user_config("NORD"), _user_config("CNOR"), _user_config("CNOR")])


def _build_node(visitor: ConfigVisitor | None = None) -> PULL_DAM_FTP:
    visitor = visitor or _build_visitor()
    node = PULL_DAM_FTP(visitor=visitor)
    node.FrcsRefDAM.setSrcRef = FFRC_DAM_2025a(visitor=visitor)
    return node


def _frame(rows: list[tuple[datetime, dict[str, float | None]]]) -> pd.DataFrame:
    normalized_rows: list[dict[str, object]] = []
    for timestamp, zone_values in rows:
        row: dict[str, object] = {"Datetime": pd.Timestamp(timestamp)}
        row.update(zone_values)
        normalized_rows.append(row)
    return pd.DataFrame(normalized_rows)


def test_config_visitor_deduplicates_market_zones() -> None:
    visitor = _build_visitor()

    assert visitor.get_market_zone_ids() == ["CNOR", "NORD"]


def test_config_visitor_single_zone_returns_single_market_zone() -> None:
    visitor = ConfigVisitor(users_config=[_user_config("CNOR"), _user_config("CNOR")])

    assert visitor.get_market_zone_ids() == ["CNOR"]


@pytest.mark.parametrize(
    ("now", "is_first_call", "last_fetch_day", "expected_method", "expected_status"),
    [
        (datetime(2026, 4, 8, 12, 0, tzinfo=ROME_TZ), True, None, "bootstrap", DamRefreshStatus.UPDATED),
        (datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ), True, None, "bootstrap", DamRefreshStatus.UPDATED),
        (
            datetime(2026, 4, 8, 12, 30, tzinfo=ROME_TZ),
            False,
            None,
            "refresh_day_ahead",
            DamRefreshStatus.SKIPPED_BEFORE_TARGET,
        ),
        (
            datetime(2026, 4, 8, 13, 13, tzinfo=ROME_TZ),
            False,
            None,
            "refresh_day_ahead",
            DamRefreshStatus.UPDATED,
        ),
        (
            datetime(2026, 4, 8, 13, 13, tzinfo=ROME_TZ),
            False,
            date(2026, 4, 8),
            "refresh_day_ahead",
            DamRefreshStatus.ALREADY_AVAILABLE,
        ),
    ],
)
def test_refresh_dispatches_based_on_time_and_state(
    now: datetime,
    is_first_call: bool,
    last_fetch_day: date | None,
    expected_method: str,
    expected_status: DamRefreshStatus,
) -> None:
    node = _build_node()
    node._first_call = is_first_call
    node._last_fetch_day = last_fetch_day

    with (
        patch.object(node, "_now_local", return_value=now),
        patch.object(
            node,
            "bootstrap",
            return_value=type("BootstrapResult", (), {"status": expected_status})(),
        ) as bootstrap,
        patch.object(
            node,
            "refresh_day_ahead",
            return_value=type("RefreshResult", (), {"status": expected_status})(),
        ) as refresh_day_ahead,
    ):
        result = node.refresh(active_zones=["NORD", "CNOR"])

    assert result.status == expected_status
    if expected_method == "bootstrap":
        bootstrap.assert_called_once_with(active_zones=["NORD", "CNOR"])
        refresh_day_ahead.assert_not_called()
    else:
        refresh_day_ahead.assert_called_once_with(active_zones=["NORD", "CNOR"])
        bootstrap.assert_not_called()


def test_bootstrap_before_cutoff_fetches_history_and_today() -> None:
    node = _build_node()
    node.FrcsRefDAM.setSrcRef.TesSmpNum = 4
    now = datetime(2026, 4, 8, 12, 0, tzinfo=ROME_TZ)
    df = _frame(
        [
            (datetime(2026, 4, 7, 23, 30), {"NORD": 100.0, "CNOR": 110.0}),
            (datetime(2026, 4, 8, 0, 0), {"NORD": 120.0, "CNOR": 130.0}),
        ]
    )

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df) as get_data:
        result = node.refresh()

    assert result.status == DamRefreshStatus.UPDATED
    assert result.updated is True
    assert node._first_call is False
    assert node._last_fetch_day is None
    get_data.assert_called_once_with(interval_start=date(2026, 4, 7), interval_end=date(2026, 4, 8))


def test_bootstrap_after_cutoff_fetches_today_and_tomorrow() -> None:
    node = _build_node()
    node.FrcsRefDAM.setSrcRef.TesSmpNum = 4
    now = datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ)
    df = _frame(
        [
            (datetime(2026, 4, 8, 23, 45), {"NORD": 120.0, "CNOR": 130.0}),
            (datetime(2026, 4, 9, 0, 0), {"NORD": 140.0, "CNOR": 150.0}),
        ]
    )

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df) as get_data:
        result = node.refresh()

    assert result.status == DamRefreshStatus.UPDATED
    assert result.updated is True
    assert node._last_fetch_day == date(2026, 4, 8)
    get_data.assert_called_once_with(interval_start=date(2026, 4, 7), interval_end=date(2026, 4, 9))


def test_bootstrap_after_cutoff_reports_missing_day_ahead_when_tomorrow_is_absent() -> None:
    node = _build_node()
    node.FrcsRefDAM.setSrcRef.TesSmpNum = 4
    now = datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ)
    df = _frame([(datetime(2026, 4, 8, 23, 45), {"NORD": 120.0, "CNOR": 130.0})])

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df):
        result = node.refresh()

    assert result.status == DamRefreshStatus.MISSING_DAY_AHEAD
    assert result.updated is True
    assert result.missing_day_ahead_zones == ("CNOR", "NORD")
    assert node._last_fetch_day is None


def test_day_ahead_refresh_merges_by_timestamp_without_duplicates() -> None:
    node = _build_node()
    series = node.FrcsRefDAM.setSrcRef.DamPrcTes["NORD"]
    series.t = datetime(2026, 4, 8, 23, 30)
    series.smpRate = timedelta(minutes=15)
    series.smpNum = 2
    series.val = [100.0, 101.0]
    series.q = []
    node._first_call = False

    now = datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ)
    df = _frame(
        [
            (datetime(2026, 4, 8, 23, 45), {"NORD": 999.0}),
            (datetime(2026, 4, 9, 0, 0), {"NORD": 200.0}),
        ]
    )

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df):
        result = node.refresh_day_ahead(active_zones=["NORD"])

    assert result.status == DamRefreshStatus.UPDATED
    assert result.updated is True
    assert node._last_fetch_day == date(2026, 4, 8)
    assert series.val == [100.0, 999.0, 200.0]
    assert series.smpNum == 3


def test_day_ahead_refresh_trims_oldest_samples_when_capacity_is_exceeded() -> None:
    node = _build_node()
    series = node.FrcsRefDAM.setSrcRef.DamPrcTes["NORD"]
    series.t = datetime(2026, 4, 8, 0, 0)
    series.smpRate = timedelta(minutes=15)
    series.smpNum = 3
    series.val = [10.0, 20.0, 30.0]
    series.q = []
    node.FrcsRefDAM.setSrcRef.TesSmpNum = 3
    node._first_call = False

    now = datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ)
    df = _frame(
        [
            (datetime(2026, 4, 8, 0, 45), {"NORD": 40.0}),
            (datetime(2026, 4, 8, 1, 0), {"NORD": 50.0}),
        ]
    )

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df):
        result = node.refresh_day_ahead(active_zones=["NORD"])

    assert result.status == DamRefreshStatus.MISSING_DAY_AHEAD
    assert result.updated is True
    assert series.t == datetime(2026, 4, 8, 0, 30)
    assert series.val == [30.0, 40.0, 50.0]
    assert series.smpNum == 3


def test_day_ahead_refresh_missing_zone_keeps_existing_series_and_stays_pending() -> None:
    node = _build_node()
    cner = node.FrcsRefDAM.setSrcRef.DamPrcTes["CNOR"]
    cner.t = datetime(2026, 4, 8, 0, 0)
    cner.smpRate = timedelta(minutes=15)
    cner.smpNum = 2
    cner.val = [10.0, 11.0]
    cner.q = []
    node._first_call = False

    now = datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ)
    df = _frame([(datetime(2026, 4, 9, 0, 0), {"NORD": 200.0})])

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df):
        result = node.refresh_day_ahead(active_zones=["NORD", "CNOR"])

    assert result.status == DamRefreshStatus.MISSING_DAY_AHEAD
    assert result.updated is True
    assert result.missing_day_ahead_zones == ("CNOR",)
    assert cner.val == [10.0, 11.0]
    assert cner.smpNum == 2


def test_day_ahead_refresh_marks_success_once_all_zones_have_tomorrow_across_retries() -> None:
    node = _build_node()
    node._first_call = False
    now = datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ)

    with patch.object(node, "_now_local", return_value=now), patch.object(
        node,
        "_get_data",
        side_effect=[
            _frame([(datetime(2026, 4, 9, 0, 0), {"NORD": 200.0})]),
            _frame([(datetime(2026, 4, 9, 0, 0), {"CNOR": 300.0})]),
        ],
    ):
        first_result = node.refresh_day_ahead(active_zones=["NORD", "CNOR"])
        second_result = node.refresh_day_ahead(active_zones=["NORD", "CNOR"])

    assert first_result.status == DamRefreshStatus.MISSING_DAY_AHEAD
    assert first_result.updated is True
    assert first_result.missing_day_ahead_zones == ("CNOR",)
    assert second_result.status == DamRefreshStatus.UPDATED
    assert second_result.updated is True
    assert node._last_fetch_day == date(2026, 4, 8)


def test_empty_payload_keeps_existing_series_unchanged() -> None:
    node = _build_node()
    series = node.FrcsRefDAM.setSrcRef.DamPrcTes["NORD"]
    series.t = datetime(2026, 4, 8, 0, 0)
    series.smpRate = timedelta(minutes=15)
    series.smpNum = 2
    series.val = [10.0, 20.0]
    series.q = []
    node._first_call = False

    now = datetime(2026, 4, 8, 13, 20, tzinfo=ROME_TZ)
    df = _frame([])

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df):
        result = node.refresh_day_ahead(active_zones=["NORD"])

    assert result.status == DamRefreshStatus.MISSING_DAY_AHEAD
    assert result.updated is False
    assert series.t == datetime(2026, 4, 8, 0, 0)
    assert series.val == [10.0, 20.0]
    assert series.smpNum == 2


def test_day_ahead_refresh_before_cutoff_is_skipped() -> None:
    node = _build_node()
    node._first_call = False
    now = datetime(2026, 4, 8, 12, 30, tzinfo=ROME_TZ)

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data") as get_data:
        result = node.refresh_day_ahead(active_zones=["NORD", "CNOR"])

    assert result.status == DamRefreshStatus.SKIPPED_BEFORE_TARGET
    assert result.updated is False
    get_data.assert_not_called()


def test_bootstrap_with_single_zone_configuration_updates_only_that_zone() -> None:
    visitor = ConfigVisitor(users_config=[_user_config("CNOR"), _user_config("CNOR")])
    node = _build_node(visitor=visitor)
    node.FrcsRefDAM.setSrcRef.TesSmpNum = 2
    now = datetime(2026, 4, 8, 12, 0, tzinfo=ROME_TZ)
    df = _frame([(datetime(2026, 4, 8, 0, 0), {"CNOR": 130.0})])

    with patch.object(node, "_now_local", return_value=now), patch.object(node, "_get_data", return_value=df):
        result = node.refresh()

    assert result.status == DamRefreshStatus.UPDATED
    assert result.updated is True
    assert node.FrcsRefDAM.setSrcRef.DamPrcTes["CNOR"].val == [130.0]
    assert node.FrcsRefDAM.setSrcRef.DamPrcTes["NORD"].val == []
