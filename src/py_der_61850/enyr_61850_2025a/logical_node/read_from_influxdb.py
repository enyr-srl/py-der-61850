import math
import os
from datetime import datetime
from typing import cast

import pandas as pd
from loguru import logger

from py_der_61850.clients.influxdb_client import InfluxClient
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_GN_2025a import FFRC_GN_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a
from py_der_61850.enyr_61850_2025a.logical_node.LNodeType import LNodeType
from py_der_61850.models.config_visitor import ConfigVisitor


class PULL_FROM_INFLUXDB(LNodeType):

    def __init__(self, visitor: ConfigVisitor) -> None:
        super().__init__(visitor=visitor)
        self._url: str = os.getenv("INFLUXDB_URL", "")
        self._token: str = os.getenv("INFLUXDB_TOKEN", "")
        self._org: str = os.getenv("INFLUXDB_ORG", "enyr")
        self._bucket: str = os.getenv("INFLUXDB_BUCKET", "mise")
        self._start: str = "-30m"
        self._stop: str = "now()"
        self._base_field: str
        self._tags: dict[str, str] | None = None
        self._last_update: datetime | None = None

    def _get_data(
        self,
        measurement: str,
        field: str,
        start: str | None = None,
        stop: str | None = None,
        extras: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Connect to InfluxDB, fetch data for the given time range,
        return as DataFrame.
        """
        client = InfluxClient(url=self._url, token=self._token, org=self._org)

        query_extras = extras if extras is not None else self._get_query_extras()
        data = client.get(
            bucket=self._bucket,
            measurement=measurement,
            fields=[field],
            start=start if start else self._start,
            stop=stop if stop else self._stop,
            tags=self._tags,
            extras=query_extras,
        )
        df = pd.DataFrame(data)
        return df

    def _get_query_extras(self) -> list[str]:
        return []

    @staticmethod
    def _get_signed_energy_query_extras(expected_sign: int) -> list[str]:
        if expected_sign not in {-1, 1}:
            raise ValueError("expected_sign must be -1 or 1")

        sign_map = (
            "map(fn: (r) => ({r with _value: if r._value < 0.0 then r._value * -1.0 else r._value}))"
            if expected_sign > 0
            else "map(fn: (r) => ({r with _value: if r._value < 0.0 then r._value else r._value * -1.0}))"
        )
        return [
            "aggregateWindow(every: 5m, fn: last, createEmpty: true)",
            "fill(usePrevious: true)",
            "movingAverage(n: 6)",
            "aggregateWindow(every: 15m, fn: last)",
            "difference()",
            sign_map,
            "timeShift(duration: -15m)",
        ]

    @staticmethod
    def _normalize_numeric_sample(value: object) -> float | None:
        if pd.isna(value):
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value):
            return None
        return numeric_value

    @staticmethod
    def _quality_for_sample(value: float | None) -> Quality_2025a:
        return Quality_2025a(0) if value is not None else Quality_2025a(1)

    def _build_samples_from_dataframe(
        self,
        df: pd.DataFrame,
        measurement: str,
        field: str,
        start: str | None = None,
        stop: str | None = None,
    ) -> tuple[list[float | None], list[Quality_2025a]]:
        ordered_df = df.sort_values("Datetime").reset_index(drop=True)
        normalized_values = [self._normalize_numeric_sample(value) for value in ordered_df["value"].tolist()]
        qualities = [self._quality_for_sample(value) for value in normalized_values]
        return normalized_values, qualities

    @staticmethod
    def _quality_rank(quality: object) -> int:
        """Rank a quality value for de-duplication (lower is better)."""
        validity = getattr(quality, "validity", quality)
        name = str(getattr(validity, "name", validity)).lower()
        return {"good": 0, "questionable": 1, "invalid": 2}.get(name, 3)

    def _collapse_duplicate_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        """Keep a single best row per timestamp.

        InfluxDB returns one series per tag-set, so the same field comes back split by its
        ``quality`` tag (e.g. a live ``good`` series plus a stale ``questionable`` one). Pulling
        them together produces duplicate timestamps that corrupt the uniform-grid assumption of
        the TES downstream. We keep one row per timestamp, preferring a finite value and the
        best quality. No-op when timestamps are already unique (e.g. single-series test data).
        """
        if df.empty or "Datetime" not in df.columns:
            return df
        ranked = df.copy()
        if "quality" in ranked.columns:
            ranked["_q_rank"] = ranked["quality"].map(self._quality_rank)
        else:
            ranked["_q_rank"] = 3
        ranked["_finite_rank"] = ranked["value"].map(
            lambda value: 0 if self._normalize_numeric_sample(value) is not None else 1
        )
        ranked = (
            ranked.sort_values(["Datetime", "_finite_rank", "_q_rank"])
            .drop_duplicates(subset="Datetime", keep="first")
            .drop(columns=["_finite_rank", "_q_rank"])
            .reset_index(drop=True)
        )
        return ranked

    def _reindex_samples_to_grid(self, datetimes, values, qualities, sample_rate):
        """Place (datetime, value, quality) triples on a uniform ``sample_rate`` grid.

        Guarantees ``val[i]`` corresponds to ``t0 + i * sample_rate`` so consumers (FFRC_*) that
        assume regular spacing read the correct calendar instant even when slots are missing
        (cold start / gaps / dropped windows). Missing slots become ``None`` (invalid quality).
        """
        grid_times = [timestamp for timestamp in datetimes if timestamp is not None]
        if not grid_times or sample_rate.total_seconds() <= 0:
            return None, list(values), list(qualities)
        t0 = min(grid_times)
        size = int(round((max(grid_times) - t0) / sample_rate)) + 1
        out_values: list = [None] * size
        out_qualities: list = [self._quality_for_sample(None) for _ in range(size)]
        for timestamp, value, quality in zip(datetimes, values, qualities):
            if timestamp is None:
                continue
            index = int(round((timestamp - t0) / sample_rate))
            if not 0 <= index < size:
                continue
            already_finite = self._normalize_numeric_sample(out_values[index]) is not None
            is_finite = self._normalize_numeric_sample(value) is not None
            if not already_finite or is_finite:
                out_values[index] = value
                out_qualities[index] = quality
        return t0, out_values, out_qualities

    def _first_call_pull_strategy(self, source_field: str, target_field: str, user_id: str) -> None:
        """
        Fetch historical data for the initial call and populate TES object.

        Parameters
        ----------
        source_field : str
            Dot-separated attribute path under `self` that resolves to the source logical node
            (e.g., "FfrcGn", "FfrcLod", "FrcsRefLOD.setSrcRef" or "FrrcsRefGN.setSrcRef").

        target_field : str
            Name of the attribute in the resolved logical node that holds the TES dictionary
            (e.g., "GnEnTotTes" or "LodEnTotTes").
        """

        measurement = user_id
        field = f"{user_id}_{self._base_field}"

        # Split nested attribute path, e.g., "FrcsRefLOD.setSrcRef" or "FrrcsRefGN.setSrcRef"
        attribute_path_parts = source_field.split(".")

        # Traverse attributes starting from `self`
        current_object = self
        resolved_source_node = None

        for part in attribute_path_parts:
            resolved_source_node = getattr(current_object, part)
            current_object = resolved_source_node

        if resolved_source_node is None:
            raise ValueError(f"Could not resolve source logical node from path '{source_field}'.")

        # Correct type cast for clarity
        resolved_source_node = cast(FFRC_GN_2025a | FFRC_LOD_2025a, resolved_source_node)
        # Determine the time range based on TES sample number and rate
        rate = int(resolved_source_node.TesSmpRate.total_seconds() // 60)
        start = f"-{resolved_source_node.TesSmpNum // (24 * (60 // rate))}d"  # Number of days to fetch based on TES sample number

        # Fetch data from InfluxDB
        df = self._get_data(start=start, stop=self._stop, measurement=measurement, field=field)
        df = self._collapse_duplicate_timestamps(df)
        if not df.empty:
            ordered_df = df.sort_values("Datetime").reset_index(drop=True)
            normalized_values, qualities = self._build_samples_from_dataframe(
                ordered_df,
                measurement=measurement,
                field=field,
                start=start,
                stop=self._stop,
            )
            datetimes = [
                value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
                for value in ordered_df["Datetime"].tolist()
            ]
            aligned_start, aligned_values, aligned_qualities = self._reindex_samples_to_grid(
                datetimes, normalized_values, qualities, resolved_source_node.TesSmpRate
            )

            # Create and populate TES object (regular grid: val[i] == t + i * smpRate)
            tes = TES_2025a()
            tes.t = aligned_start if aligned_start is not None else datetimes[0]
            tes.smpRate = resolved_source_node.TesSmpRate
            tes.val = aligned_values
            tes.q = aligned_qualities
            tes.smpNum = len(aligned_values)

            target_attribute = getattr(
                resolved_source_node, target_field
            )  # e.g., self.FfrcGn.GnEnTotTes or self.FfrcLod.LodEnTotTes
            target_attribute[user_id] = tes
        else:
            logger.warning(f"No data fetched from InfluxDB for field: {field}")

    def _ref_call_pull_strategy(self, source_field: str, target_field: str, user_id: str) -> None:
        """
        Fetch historical data for the reference call and populate TES object.

        Parameters
        ----------
        source_field : str
            Name of the attribute in self that holds the source logical node (e.g., 'FfrcGn', 'FfrcLod', "FrcsRefLOD.setSrcRef" or "FrrcsRefGN.setSrcRef").
        target_field : str
            Name of the attribute in the source logical node that holds the TES dictionary (e.g., 'GnEnTotTes' or 'LodEnTotTes').
        """
        measurement = user_id
        field = f"{user_id}_{self._base_field}"

        # Fetch data from InfluxDB
        df = self._get_data(measurement=measurement, field=field)
        df = self._collapse_duplicate_timestamps(df)
        if not df.empty:
            ordered_df = df.sort_values("Datetime").reset_index(drop=True)
            normalized_values, qualities = self._build_samples_from_dataframe(
                ordered_df,
                measurement=measurement,
                field=field,
                start=self._start,
                stop=self._stop,
            )
            normalized_value = normalized_values[0]
            sample_quality = qualities[0]

            # Split nested attribute path, e.g., "FrcsRefLOD.setSrcRef" or "FrrcsRefGN.setSrcRef"
            attribute_path_parts = source_field.split(".")

            # Traverse attributes starting from `self`
            current_object = self
            resolved_source_node = None

            for part in attribute_path_parts:
                resolved_source_node = getattr(current_object, part)
                current_object = resolved_source_node

            if resolved_source_node is None:
                raise ValueError(f"Could not resolve source logical node from path '{source_field}'.")

            # Correct type cast for clarity
            resolved_source_node = cast(FFRC_GN_2025a | FFRC_LOD_2025a, resolved_source_node)

            target_attribute = getattr(
                resolved_source_node, target_field
            )  # e.g., self.FfrcGn.GnEnTotTes or self.FfrcLod.LodEnTotTes

            # Append new integral value and quality
            target_attribute[user_id].val.append(normalized_value)
            target_attribute[user_id].q.append(sample_quality)

            # Maintain the size of the TES list within the defined sample number
            if len(target_attribute[user_id].val) > resolved_source_node.TesSmpNum:
                target_attribute[user_id].val.pop(0)
                first_time = target_attribute[user_id].t

                # Update the start time if it exists (shift forward by one sample)
                if first_time:
                    first_time += resolved_source_node.TesSmpRate
                    target_attribute[user_id].t = first_time

        else:
            logger.warning(f"No data fetched from InfluxDB for field: {field}")

    def __call__(self) -> None:
        pass
