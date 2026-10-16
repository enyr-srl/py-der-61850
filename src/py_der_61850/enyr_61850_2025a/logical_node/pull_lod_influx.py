import logging
from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_objects.ORG_Frcs_LOD_2025a import ORG_Frcs_LOD_2025a
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.logical_node.read_from_influxdb import PULL_FROM_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor


class PULL_LOD_INFLUXDB(PULL_FROM_INFLUXDB):

    # Auto-riparazione dello storico incrementale: il ref-pull appende un solo campione
    # per ciclo e fa scorrere la griglia; nel tempo un disallineamento o una raffica di
    # None puo' degradare la serie a punto tale che FFRC_LOD non trova piu' i giorni di
    # riferimento (forecast piatto/questionable o non-finite). Un pull completo la
    # riallinea alla griglia wall-clock. Ri-bootstrappiamo quando la serie e' degradata
    # e comunque periodicamente, per tappare la deriva a monte invece di degradare in
    # silenzio per giorni.
    _MIN_FINITE_RATIO: float = 0.6
    _MIN_SAMPLES_TO_JUDGE: int = 200  # non giudicare serie ancora in riempimento (i test usano poche decine)
    _REBOOTSTRAP_EVERY_CYCLES: int = 96  # ~1 giorno a 15 min

    def __init__(self, visitor: ConfigVisitor) -> None:
        self._base_field: str = "load_MMTN1.DmdWh.actVal"
        super().__init__(visitor=visitor)
        self._first_call: bool = True
        self._cycles_since_bootstrap: int = 0
        self.FrcsRefLOD: ORG_Frcs_LOD_2025a = ORG_Frcs_LOD_2025a()
        self._logger = logging.getLogger(__name__)

    def _is_tes_degraded(self, tes) -> bool:
        """True quando la serie incrementale, ormai a regime, non e' piu' utilizzabile per
        una previsione: troppi campioni non-finiti (None/NaN). Una serie ancora corta (in
        riempimento) non e' degradata: si giudica solo quando ha raggiunto una lunghezza
        significativa."""
        values = getattr(tes, "val", None) or []
        if len(values) < self._MIN_SAMPLES_TO_JUDGE:
            return False
        finite = sum(1 for v in values if self._normalize_numeric_sample(v) is not None)
        return finite < max(1, int(self._MIN_FINITE_RATIO * len(values)))

    def _get_query_extras(self) -> list[str]:
        # LodEnTotTes must be negative quarter-hour energy from DmdWh counters.
        return self._get_signed_energy_query_extras(expected_sign=-1)

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
                "[PULL_LOD_INFLUXDB] Invalidated %d load samples for '%s' due to missing raw Influx windows at %s%s",
                len(invalidated_timestamps),
                measurement,
                shown_timestamps,
                suffix,
            )

        return masked_values, masked_qualities

    def __call__(self) -> None:
        now = datetime.now()
        forecast_node = self.FrcsRefLOD.setSrcRef
        users = self._visitor._rec_config["users"]
        missing_users = [user_id for user_id in users if user_id not in forecast_node.LodEnTotTes]

        if (
            not self._first_call
            and self._last_update
            and (now - self._last_update).total_seconds() <= forecast_node.TesSmpRate.total_seconds()
        ):
            for user_id in missing_users:
                self._first_call_pull_strategy("FrcsRefLOD.setSrcRef", "LodEnTotTes", user_id)
            if missing_users:
                self._last_update = now
            return

        periodic_rebootstrap = self._cycles_since_bootstrap >= self._REBOOTSTRAP_EVERY_CYCLES
        did_bootstrap = False
        for user_id in users:
            tes = forecast_node.LodEnTotTes.get(user_id)
            if self._first_call or tes is None:
                self._first_call_pull_strategy("FrcsRefLOD.setSrcRef", "LodEnTotTes", user_id)
                did_bootstrap = True
            elif periodic_rebootstrap or self._is_tes_degraded(tes):
                reason = "periodica" if periodic_rebootstrap else "storico degradato (troppi campioni non-finiti)"
                self._logger.warning(
                    f"[PULL_LOD] Ri-bootstrap dello storico di carico per '{user_id}' ({reason}): "
                    f"pull completo per riallineare la serie."
                )
                self._first_call_pull_strategy("FrcsRefLOD.setSrcRef", "LodEnTotTes", user_id)
                did_bootstrap = True
            else:
                self._ref_call_pull_strategy("FrcsRefLOD.setSrcRef", "LodEnTotTes", user_id)
        self._last_update = now
        self._first_call = False
        self._cycles_since_bootstrap = 0 if did_bootstrap else self._cycles_since_bootstrap + 1
