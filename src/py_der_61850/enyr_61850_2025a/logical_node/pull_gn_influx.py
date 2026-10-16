import os
from datetime import datetime
import logging

from loguru import logger

from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.ORG_Frcs_GN_2025a import ORG_Frcs_GN_2025a
from py_der_61850.enyr_61850_2025a.logical_node.read_from_influxdb import PULL_FROM_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class PULL_GN_INFLUXDB(PULL_FROM_INFLUXDB):

    def __init__(self, visitor: ConfigVisitor) -> None:
        self._base_field: str = "pv_MMTN1.SupWh.actVal"
        super().__init__(visitor=visitor)
        # Override field if needed
        self._user_id: str = os.getenv("INFLUXDB_USER_ID", "PODXX1")
        self._first_call: bool = True
        self.FrcsRefGN: ORG_Frcs_GN_2025a = ORG_Frcs_GN_2025a()
        self._logger = logging.getLogger(__name__)

    def _get_query_extras(self) -> list[str]:
        # GnEnTotTes must be positive quarter-hour energy from SupWh counters.
        return self._get_signed_energy_query_extras(expected_sign=1)

    def _get_presence_query_extras(self) -> list[str]:
        return [
            "aggregateWindow(every: 15m, fn: count, createEmpty: true)",
            "timeShift(duration: -15m)",
        ]

    def _build_samples_from_dataframe(
        self,
        df,
        measurement: str,
        field: str,
        start: str | None = None,
        stop: str | None = None,
    ) -> tuple[list[float | None], list[Quality_2025a]]:
        ordered_df = df.sort_values("Datetime").reset_index(drop=True)
        normalized_values, qualities = super()._build_samples_from_dataframe(
            ordered_df,
            measurement=measurement,
            field=field,
            start=start,
            stop=stop,
        )
        presence_df = self._get_data(
            measurement=measurement,
            field=field,
            start=start,
            stop=stop,
            extras=self._get_presence_query_extras(),
        )
        if presence_df.empty:
            return normalized_values, qualities

        ordered_presence_df = presence_df.sort_values("Datetime").reset_index(drop=True)
        presence_by_time = {
            row.Datetime: int(row.value) if row.value is not None else 0
            for row in ordered_presence_df.itertuples(index=False)
        }

        masked_values: list[float | None] = []
        masked_qualities: list[Quality_2025a] = []
        invalidated_timestamps: list[str] = []
        previous_presence: int | None = None

        for index, row in enumerate(ordered_df.itertuples(index=False)):
            timestamp = row.Datetime
            current_presence = presence_by_time.get(timestamp, 0)
            effective_previous_presence = current_presence if previous_presence is None else previous_presence
            value = normalized_values[index]

            if value is None or current_presence <= 0 or effective_previous_presence <= 0:
                masked_values.append(None)
                masked_qualities.append(self._quality_for_sample(None))
                if value is not None:
                    invalidated_timestamps.append(timestamp.isoformat())
            else:
                masked_values.append(value)
                masked_qualities.append(qualities[index])

            previous_presence = current_presence

        if invalidated_timestamps:
            shown_timestamps = invalidated_timestamps[:5]
            suffix = "..." if len(invalidated_timestamps) > 5 else ""
            self._logger.warning(
                "[PULL_GN_INFLUXDB] Invalidated %d generation samples for '%s' due to missing raw Influx windows at %s%s",
                len(invalidated_timestamps),
                measurement,
                shown_timestamps,
                suffix,
            )

        return masked_values, masked_qualities

    def __call__(self) -> None:
        now = datetime.now()
        for user_id in self._visitor._rec_config["users"]:
            if self._first_call:
                self._first_call_pull_strategy("FrcsRefGN.setSrcRef", "GnEnTotTes", user_id)
            elif (
                self._last_update
                and (now - self._last_update).total_seconds() <= self.FrcsRefGN.setSrcRef.TesSmpRate.total_seconds()
            ):
                return  # Avoid multiple fetches within the sampling rate interval
            else:
                try:
                    self._ref_call_pull_strategy("FrcsRefGN.setSrcRef", "GnEnTotTes", user_id)
                except Exception as e:
                    logger.warning(f"Failed to pull data from InfluxDB: {e}")
        self._last_update = now
        self._first_call = False
