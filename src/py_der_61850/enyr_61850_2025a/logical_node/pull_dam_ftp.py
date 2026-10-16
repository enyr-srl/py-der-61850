import os
from dataclasses import dataclass
from enum import Enum
from math import ceil
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from py_der_61850.clients.gme_api_client import GMEApiClient
from py_der_61850.enyr_61850_2025a.data_objects.ORG_Frcs_DAM_2025a import ORG_Frcs_DAM_2025a
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor

ROME_TZ = ZoneInfo("Europe/Rome")


class DamRefreshStatus(str, Enum):
    UPDATED = "updated"
    ALREADY_AVAILABLE = "already_available"
    MISSING_DAY_AHEAD = "missing_day_ahead"
    SKIPPED_BEFORE_TARGET = "skipped_before_target"


@dataclass(frozen=True)
class DamRefreshResult:
    status: DamRefreshStatus
    updated: bool = False
    missing_day_ahead_zones: tuple[str, ...] = ()


class PULL_DAM_FTP(LNodeType):

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)
        self._username: str = os.getenv("GME_USERNAME", "")
        self._password: str = os.getenv("GME_PASSWORD", "")
        self.target_time: str = "13:13"
        self._first_call: bool = True
        self._last_fetch_day: date | None = None
        self.FrcsRefDAM: ORG_Frcs_DAM_2025a = ORG_Frcs_DAM_2025a()

    def _now_local(self) -> datetime:
        return datetime.now(ROME_TZ)

    def _is_after_target_time(self, now: datetime | None = None) -> bool:
        reference = now or self._now_local()
        hour, minute = map(int, self.target_time.split(":"))
        target_time = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return reference >= target_time

    def _get_data(self, interval_start: date, interval_end: date) -> pd.DataFrame:
        gme_client = GMEApiClient(username=self._username, password=self._password)
        data = gme_client.fetch_mgp_zonal_prices(interval_start, interval_end)
        df_raw = gme_client.convert_date(data)
        df = gme_client.pivot(df_raw)
        df = df.sort_values(by="Datetime").reset_index(drop=True)
        return df

    def _history_days(self) -> int:
        samples_per_day = 24 * 4
        return max(1, ceil(self.FrcsRefDAM.setSrcRef.TesSmpNum / samples_per_day))

    def _resolve_active_zones(self, active_zones: list[str] | None) -> list[str]:
        if active_zones:
            return sorted({zone.upper() for zone in active_zones})

        visitor_zones = self._visitor.get_market_zone_ids()
        if visitor_zones:
            return visitor_zones

        return list(self.FrcsRefDAM.setSrcRef.MrkZnIds)

    def _series_to_samples(self, zone: str) -> dict[datetime, tuple[float | None, Quality_2025a]]:
        series = self.FrcsRefDAM.setSrcRef.DamPrcTes[zone]
        if series.t is None:
            return {}

        sample_rate = series.smpRate or self.FrcsRefDAM.setSrcRef.TesSmpRate
        timestamp = series.t
        quality_values = list(series.q or [])
        samples: dict[datetime, tuple[float | None, Quality_2025a]] = {}

        for index, value in enumerate(series.val):
            quality = quality_values[index] if index < len(quality_values) else self._quality_for_value(value)
            samples[timestamp] = (value, quality)
            timestamp += sample_rate

        return samples

    @staticmethod
    def _quality_for_value(value: float | None) -> Quality_2025a:
        return Quality_2025a(1 if pd.notna(value) else 2)

    @staticmethod
    def _quality_signature(qualities: list[Quality_2025a]) -> list[int]:
        return [quality.validity.value for quality in qualities]

    def _series_matches(
        self,
        zone: str,
        ordered_timestamps: list[datetime],
        values: list[float | None],
        qualities: list[Quality_2025a],
    ) -> bool:
        series = self.FrcsRefDAM.setSrcRef.DamPrcTes[zone]
        if not ordered_timestamps:
            return series.t is None and not series.val

        return (
            series.t == ordered_timestamps[0]
            and series.smpRate == self.FrcsRefDAM.setSrcRef.TesSmpRate
            and series.smpNum == len(ordered_timestamps)
            and list(series.val) == values
            and self._quality_signature(list(series.q or [])) == self._quality_signature(qualities)
        )

    def _upsert_zone_series(self, zone: str, df: pd.DataFrame) -> bool:
        if zone not in df.columns:
            logger.warning(f"PULL_DAM_FTP: zone '{zone}' not found in GME payload. Keeping existing TES unchanged.")
            return False

        samples = self._series_to_samples(zone)
        datetimes = pd.to_datetime(df["Datetime"], errors="coerce")

        for timestamp_value, raw_value in zip(datetimes, df[zone].tolist(), strict=True):
            if pd.isna(timestamp_value):
                continue
            timestamp = timestamp_value.to_pydatetime()
            samples[timestamp] = (raw_value, self._quality_for_value(raw_value))

        if not samples:
            return False

        ordered_timestamps = sorted(samples)
        max_samples = self.FrcsRefDAM.setSrcRef.TesSmpNum
        if len(ordered_timestamps) > max_samples:
            ordered_timestamps = ordered_timestamps[-max_samples:]

        values = [samples[timestamp][0] for timestamp in ordered_timestamps]
        qualities = [samples[timestamp][1] for timestamp in ordered_timestamps]
        if self._series_matches(zone, ordered_timestamps, values, qualities):
            return False

        series = self.FrcsRefDAM.setSrcRef.DamPrcTes[zone]
        series.t = ordered_timestamps[0]
        series.smpRate = self.FrcsRefDAM.setSrcRef.TesSmpRate
        series.smpNum = len(ordered_timestamps)
        series.val = values
        series.q = qualities
        return True

    def _series_has_day_ahead_data(self, zone: str, today: date) -> bool:
        series = self.FrcsRefDAM.setSrcRef.DamPrcTes[zone]
        if series.t is None:
            return False

        sample_rate = series.smpRate or self.FrcsRefDAM.setSrcRef.TesSmpRate
        timestamp = series.t
        for value in series.val:
            if pd.notna(value) and timestamp.date() > today:
                return True
            timestamp += sample_rate
        return False

    def _missing_day_ahead_zones(self, active_zones: list[str], today: date) -> tuple[str, ...]:
        return tuple(zone for zone in active_zones if not self._series_has_day_ahead_data(zone, today))

    def _apply_frame(self, df: pd.DataFrame, active_zones: list[str]) -> bool:
        if df.empty:
            logger.warning("PULL_DAM_FTP: empty GME payload received. Keeping existing DAM TES unchanged.")
            return False

        updated = False
        for zone in active_zones:
            updated = self._upsert_zone_series(zone, df) or updated
        return updated

    def _result_for_state(self, now: datetime, today: date, active_zones: list[str], updated: bool) -> DamRefreshResult:
        if self._is_after_target_time(now):
            missing_day_ahead_zones = self._missing_day_ahead_zones(active_zones, today)
            if missing_day_ahead_zones:
                return DamRefreshResult(
                    status=DamRefreshStatus.MISSING_DAY_AHEAD,
                    updated=updated,
                    missing_day_ahead_zones=missing_day_ahead_zones,
                )
            self._last_fetch_day = today

        return DamRefreshResult(status=DamRefreshStatus.UPDATED, updated=updated)

    def bootstrap(self, active_zones: list[str] | None = None) -> DamRefreshResult:
        now = self._now_local()
        today = now.date()
        interval_end = today + timedelta(days=1 if self._is_after_target_time(now) else 0)
        interval_start = today - timedelta(days=self._history_days())
        zones = self._resolve_active_zones(active_zones)

        df = self._get_data(interval_start=interval_start, interval_end=interval_end)
        updated = self._apply_frame(df=df, active_zones=zones)

        self._first_call = False

        return self._result_for_state(now=now, today=today, active_zones=zones, updated=updated)

    def refresh_day_ahead(self, active_zones: list[str] | None = None) -> DamRefreshResult:
        now = self._now_local()
        today = now.date()

        if not self._is_after_target_time(now):
            logger.info("PULL_DAM_FTP: day-ahead refresh skipped because the publication cutoff has not been reached yet.")
            return DamRefreshResult(status=DamRefreshStatus.SKIPPED_BEFORE_TARGET, updated=False)

        if self._last_fetch_day == today:
            logger.info(f"PULL_DAM_FTP: day-ahead data for {today.isoformat()} already refreshed.")
            return DamRefreshResult(status=DamRefreshStatus.ALREADY_AVAILABLE, updated=False)

        zones = self._resolve_active_zones(active_zones)
        df = self._get_data(interval_start=today, interval_end=today + timedelta(days=1))
        updated = self._apply_frame(df=df, active_zones=zones)

        return self._result_for_state(now=now, today=today, active_zones=zones, updated=updated)

    def refresh(self, active_zones: list[str] | None = None) -> DamRefreshResult:
        if self._first_call:
            return self.bootstrap(active_zones=active_zones)
        return self.refresh_day_ahead(active_zones=active_zones)

    def __call__(self) -> None:
        self.refresh()
