from datetime import datetime, timezone

import pandas as pd
from loguru import logger

from py_der_61850.enyr_61850_2025a.data_objects.ORG_Frcs_GN_2025a import ORG_Frcs_GN_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.read_from_influxdb import PULL_FROM_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class PULL_HORINSOL_INFLUXDB(PULL_FROM_INFLUXDB):

    def __init__(self, visitor: ConfigVisitor) -> None:
        self._base_field: str = "shortwave_radiation"
        super().__init__(visitor=visitor)
        self.FrcsRefGN: ORG_Frcs_GN_2025a = ORG_Frcs_GN_2025a()
        self._start: str
        self._stop: str
        self._first_call: bool = True

    def _get_latest_iconeu_run_hour(self) -> str:
        now = datetime.now(tz=timezone.utc)
        hour = now.hour
        if 3 <= hour < 9:
            return "00"
        elif 9 <= hour < 16:
            return "06"
        elif 16 <= hour < 21:
            return "12"
        else:
            return "18"

    def _build_tags(self, user_id: str) -> None:
        self._tags = {}
        run = self._get_latest_iconeu_run_hour()
        self._tags["run"] = run
        if user_id is not None:
            self._tags["user_id"] = user_id

    def _align_weather_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["Datetime", "value"])

        ordered_df = df[["Datetime", "value"]].copy()
        ordered_df["Datetime"] = pd.to_datetime(ordered_df["Datetime"], utc=True)
        ordered_df["value"] = [
            self._normalize_numeric_sample(value)
            for value in ordered_df["value"].tolist()
        ]
        ordered_df = (
            ordered_df.sort_values("Datetime")
            .drop_duplicates(subset=["Datetime"], keep="last")
            .reset_index(drop=True)
        )

        if ordered_df.empty:
            return pd.DataFrame(columns=["Datetime", "value"])

        sample_rate = self.FrcsRefGN.setSrcRef.FrcsSmpRate
        timeline = pd.date_range(
            start=ordered_df.at[0, "Datetime"],
            end=ordered_df.at[len(ordered_df) - 1, "Datetime"],
            freq=sample_rate,
        )
        aligned_df = pd.DataFrame({"Datetime": timeline})
        aligned_df = aligned_df.merge(ordered_df, on="Datetime", how="left")
        return aligned_df

    def _series_to_dataframe(self, series: TES_2025a) -> pd.DataFrame:
        if series.t is None or not series.val:
            return pd.DataFrame(columns=["Datetime", "value"])

        sample_rate = series.smpRate or self.FrcsRefGN.setSrcRef.FrcsSmpRate
        datetimes = pd.date_range(start=series.t, periods=len(series.val), freq=sample_rate)
        return pd.DataFrame({"Datetime": datetimes, "value": series.val})

    def _apply_dataframe_to_series(self, user_id: str, df: pd.DataFrame) -> None:
        if df.empty:
            return

        aligned_df = df.sort_values("Datetime").reset_index(drop=True)
        values = [
            self._normalize_numeric_sample(value)
            for value in aligned_df["value"].tolist()
        ]

        tes = self.FrcsRefGN.setSrcRef.HorInsolTes.setdefault(user_id, TES_2025a())
        tes.t = aligned_df.at[0, "Datetime"].to_pydatetime()
        tes.smpRate = self.FrcsRefGN.setSrcRef.FrcsSmpRate
        tes.smpNum = len(values)
        tes.val = values
        tes.q = [self._quality_for_sample(value) for value in values]

    def _merge_weather_samples(self, user_id: str, new_df: pd.DataFrame) -> pd.DataFrame:
        current_series = self.FrcsRefGN.setSrcRef.HorInsolTes.get(user_id)
        current_df = self._series_to_dataframe(current_series) if current_series is not None else pd.DataFrame()

        merged_df = (
            pd.concat([current_df, new_df], ignore_index=True)
            .sort_values("Datetime")
            .drop_duplicates(subset=["Datetime"], keep="last")
            .reset_index(drop=True)
        )

        max_samples = self.FrcsRefGN.setSrcRef.TesSmpNum + self.FrcsRefGN.setSrcRef.FrcsSmpNum
        if len(merged_df) > max_samples:
            merged_df = merged_df.iloc[-max_samples:].reset_index(drop=True)

        return merged_df

    def __call__(self) -> None:
        now = datetime.now(timezone.utc)
        for user_id in self._visitor._rec_config["users"]:
            measurement = "weather_forecasts"
            field = self._base_field
            history_window = self.FrcsRefGN.setSrcRef.TesSmpRate * self.FrcsRefGN.setSrcRef.TesSmpNum
            future_window = self.FrcsRefGN.setSrcRef.FrcsSmpRate * self.FrcsRefGN.setSrcRef.FrcsSmpNum
            self._start = (now - history_window).isoformat()
            self._stop = (now + future_window).isoformat()
            self._build_tags(user_id)
            df = self._get_data(measurement=measurement, field=field)
            if not df.empty:
                aligned_df = self._align_weather_dataframe(df)
                if self._first_call or user_id not in self.FrcsRefGN.setSrcRef.HorInsolTes:
                    self._apply_dataframe_to_series(user_id, aligned_df)
                else:
                    merged_df = self._merge_weather_samples(user_id, aligned_df)
                    self._apply_dataframe_to_series(user_id, merged_df)
            else:
                logger.warning(
                    f"[PULL HORINSOL] No data fetched from InfluxDB for measurement: {measurement}, field: {field}, user_id: {user_id}"
                )

        self._first_call = False
        self.last_update = now
