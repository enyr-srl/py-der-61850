from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ObisCode(StrEnum):
    """Codici OBIS noti per misuratori intelligenti 2G (IEC 62056)."""

    POTENZA_ATTIVA_PRELEVATA = "1-0:1.7.0.255_3,0_2"
    ENERGIA_ATTIVA_PRELEVATA = "1-0:1.8.0.255_3,0_2"
    POTENZA_ATTIVA_IMMESSA = "1-0:2.7.0.255_3,0_2"
    ENERGIA_ATTIVA_IMMESSA = "1-0:2.8.0.255_3,0_2"
    FASCIA_ORARIA = "0-0:96.14.0.255_1,0_2"
    PROFILO_QUART_PRELIEVO = "1-0:99.1.0.255_7,1_2___0"
    PROFILO_QUART_IMMISSIONE = "1-0:99.1.1.255_7,1_2___0"


class ObisDescriptorItem(BaseModel):
    obis_name: str
    obis_description: str
    unit_of_measure: str
    collection: bool

    @field_validator("collection", mode="before")
    @classmethod
    def _parse_collection(cls, v: Any) -> bool:
        return str(v).strip().lower() == "true" if isinstance(v, str) else bool(v)

    def __repr__(self) -> str:
        ts = "✓" if self.collection else "✗"
        return f"ObisDescriptorItem({self.obis_name!r}, ts={ts}, [{self.unit_of_measure}] {self.obis_description})"


class DataPoint(BaseModel):
    """Campione generico: ts + valori OBIS come campi extra (extra='allow')."""

    model_config = ConfigDict(extra="allow")

    ts: int

    @model_validator(mode="before")
    @classmethod
    def _coerce_ts(cls, data: dict) -> dict:
        d = dict(data)
        if "ts" in d:
            d["ts"] = int(d["ts"])
        return d

    @property
    def datetime_utc(self) -> datetime:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc)

    def value(self, obis: str) -> int | float | str | None:
        """Valore numerico del codice OBIS richiesto (accetta ObisCode o stringa)."""
        if not self.model_extra:
            return None
        raw = self.model_extra.get(str(obis))
        if raw is None:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            try:
                return float(raw)
            except (ValueError, TypeError):
                return raw


class LastValueResponse(BaseModel):
    du: str
    pod: str
    data: DataPoint

    @property
    def timestamp(self) -> datetime:
        return self.data.datetime_utc

    def value(self, obis: str | ObisCode) -> int | float | str | None:
        return self.data.value(str(obis))


class SeriesResponse(BaseModel):
    du: str
    pod: str
    data: list[DataPoint]

    def to_records(self, obis: str | ObisCode) -> list[dict]:
        """Lista di {datetime, value} per il codice OBIS richiesto."""
        key = str(obis)
        return [{"datetime": p.datetime_utc, "value": p.value(key)} for p in self.data]


class DuStatus(BaseModel):
    status: str
    wifi_signal: str
    in_session: str
    ts: int

    @field_validator("ts", mode="before")
    @classmethod
    def _coerce_ts(cls, v: Any) -> int:
        return int(v)

    @property
    def datetime_utc(self) -> datetime:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc)


class PodStatus(BaseModel):
    data_counter: str
    plc_data_quality: str
    ts: int

    @field_validator("ts", mode="before")
    @classmethod
    def _coerce_ts(cls, v: Any) -> int:
        return int(v)


class PodInfo(BaseModel):
    pod: str
    meter_type: str
    pod_status: PodStatus


class DeviceStatusResponse(BaseModel):
    du: str
    du_status: DuStatus
    pods: list[PodInfo]


class Chain2StatusResponse(BaseModel):
    Status: str
    Description: str


class AlfaSinapsiClient:
    """Client RESTful per le API IoMeter2G di Sinapsi SGH Cloud."""

    def __init__(self, base_url: str, api_key: str, header_key: str = "x-apikey"):
        self._client = httpx.Client(
            base_url=base_url,
            headers={header_key: api_key},
        )
        self._descriptor: list[ObisDescriptorItem] | None = None
        # self.get_obis_descriptor()

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _url_encode(self, segment: str) -> str:
        return quote(str(segment), safe="")

    def _get(self, *segments: str) -> Any:
        path = "/".join(self._url_encode(s) for s in segments)
        r = self._client.get(f"/iomtsgdata/v2/{path}")
        if not r.is_success:
            logger.warning(r.content)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _apply_multiplier(value: int | float | str | None, multiplier: float) -> int | float | str | None:
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return value

        scaled_value = value * multiplier
        if isinstance(value, int) and float(multiplier).is_integer():
            return int(scaled_value)
        return scaled_value

    def read(self, pod: str, obis: str, unit: str, activation_key: str, multiplier: float):
        logger.info(f"[AlfaSinapsiClient GET]: pod:{pod}, obis:{obis}, activation_key:{activation_key}")
        result = self.get_last_value(activation_key=activation_key, pod=pod, obis=obis)
        raw_value = result.value(obis)
        scaled_value = self._apply_multiplier(raw_value, multiplier)
        logger.info(f"Device:    {result.du}")
        logger.info(f"POD:       {result.pod}")
        logger.info(f"Potenza:   {scaled_value} W")
        logger.info(f"Timestamp: {result.timestamp.isoformat()}")
        return scaled_value

    def write(self, value: str, control_type: int):
        logger.info("[AlfaSinapsiClient WRITE]")
        pass

    # ------------------------------------------------------------------
    # GET /iomtsgdata/v2/obisdescriptor
    # ------------------------------------------------------------------
    def get_obis_descriptor(self, *, refresh: bool = False) -> list[ObisDescriptorItem]:
        """Lista grandezze OBIS disponibili. Risultato cached dopo la prima chiamata."""
        if self._descriptor is None or refresh:
            self._descriptor = [ObisDescriptorItem(**i) for i in self._get("obisdescriptor")]
        return self._descriptor

    def find_obis(self, search: str) -> list[ObisDescriptorItem]:
        """Cerca nel descriptor per nome o descrizione OBIS (case-insensitive)."""
        needle = search.lower()
        return [
            o
            for o in self.get_obis_descriptor()
            if needle in o.obis_name.lower() or needle in o.obis_description.lower()
        ]

    def collection_obis(self) -> list[ObisDescriptorItem]:
        """Restituisce solo i codici OBIS disponibili come time series."""
        return [o for o in self.get_obis_descriptor() if o.collection]

    # ------------------------------------------------------------------
    # GET /iomtsgdata/v2/{activation_key}/{pod}/{obis}
    # ------------------------------------------------------------------
    def get_last_value(self, activation_key: str, pod: str, obis: str | ObisCode) -> LastValueResponse:
        """Ultimo valore istantaneo di una grandezza OBIS per un POD."""
        response = self._get(activation_key, pod, str(obis))
        return LastValueResponse(**response)

    @staticmethod
    def to_unix(dt: datetime) -> int:
        """Helper per convertire datetime → Unix timestamp UTC"""
        return int(dt.replace(tzinfo=timezone.utc).timestamp())

    # ------------------------------------------------------------------
    # GET /iomtsgdata/v2/{activation_key}/{pod}/{obis}/{from}/{to}
    # ------------------------------------------------------------------
    def get_timeseries(
        self,
        activation_key: str,
        pod: str,
        obis: str | ObisCode,
        from_ts: datetime,
        to_ts: datetime,
    ) -> SeriesResponse:
        """Time series storica di una grandezza OBIS (max 1 mese)."""
        return SeriesResponse(
            **self._get(activation_key, pod, str(obis), str(self.to_unix(from_ts)), str(self.to_unix(to_ts)))
        )

    # ------------------------------------------------------------------
    # GET /iomtsgdata/v2/{activation_key}/{pod}/energy/loadcurve/{from}/{to}
    # ------------------------------------------------------------------
    def get_loadcurve(
        self,
        activation_key: str,
        pod: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> SeriesResponse:
        """Curva di carico energetica quartoraria del POD (max 1 mese)."""
        return SeriesResponse(
            **self._get(
                activation_key, pod, "energy", "loadcurve", str(self.to_unix(from_ts)), str(self.to_unix(to_ts))
            )
        )

    # ------------------------------------------------------------------
    # GET /iomtsgdata/v2/status/du/{activation_key}
    # ------------------------------------------------------------------
    def get_device_status(self, activation_key: str) -> DeviceStatusResponse:
        """Stato del dispositivo IoMeter2G e dei POD associati."""
        return DeviceStatusResponse(**self._get("status", "du", activation_key))

    # ------------------------------------------------------------------
    # GET /iomtsgdata/v2/last_status/pod/{pod_serial}/{cf}
    # ------------------------------------------------------------------
    def get_chain2_status(self, pod_serial: str, codice_fiscale: str) -> Chain2StatusResponse:
        """Stato attivazione servizio Chain2 per un POD."""
        return Chain2StatusResponse(**self._get("last_status", "pod", pod_serial, codice_fiscale))
