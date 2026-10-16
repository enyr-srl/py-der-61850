"""GMEApiClient — HTTP adapter for the GME public REST API."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import date, datetime, time
from typing import Any

import httpx
import pandas as pd
from loguru import logger
from pydantic import BaseModel, ConfigDict


class GMEError(RuntimeError):
    pass


class ZonalPrice(BaseModel):

    model_config = ConfigDict(frozen=True)

    flow_date: date
    hour: int
    market: str
    zone: str
    price_eur_mwh: float
    period: int

    @classmethod
    def from_api_record(cls, record: dict[str, Any]) -> ZonalPrice:
        """Parse a raw API record dict into a ZonalPrice."""
        folded = {k.casefold(): v for k, v in record.items()}

        def get(*names: str) -> Any:
            for name in names:
                if name.casefold() in folded:
                    return folded[name.casefold()]
            return None

        try:
            flow_date = datetime.strptime(str(get("FlowDate")).strip(), "%Y%m%d").date()
            hour = int(str(get("Hour")).strip())
            market = str(get("Market") or "").strip()
            zone = str(get("Zone") or "").strip().upper()
            price = float(str(get("Price")).strip().replace(",", "."))
            period = int(str(get("Period")).strip())
        except (ValueError, TypeError) as exc:
            raise GMEError(f"Cannot parse zonal price record: {record}") from exc

        return cls(
            flow_date=flow_date,
            hour=hour,
            market=market,
            zone=zone,
            price_eur_mwh=price,
            period=period,
        )


class GMEApiClient:

    def __init__(
        self,
        username: str,
        password: str,
        *,
        base_url: str = "https://api.mercatoelettrico.org",
        endpoint: str = "/request/api/v1",
        platform: str = "PublicMarketResults",
        segment: str = "MGP",
        data_name: str = "ME_ZonalPrices",
        granularity: str = "PT15",
        timeout: float = 30.0,
    ) -> None:
        self._username = username
        self._password = password
        self._base_url = base_url
        self._endpoint = endpoint
        self._platform = platform
        self._segment = segment
        self._data_name = data_name
        self._granularity = granularity
        self._timeout = timeout
        self._token: str | None = None

    def fetch_mgp_zonal_prices(
        self,
        interval_start: date,
        interval_end: date,
    ) -> list[ZonalPrice]:
        """Return PT15 MGP zonal prices for the given closed interval."""
        token = self._authenticate()
        records = self._request_records(token, interval_start, interval_end)
        prices = [ZonalPrice.from_api_record(r) for r in records]
        logger.debug("Fetched MGP zonal prices", count=len(prices))
        return prices

    def convert_date(self, prices: list[ZonalPrice]) -> pd.DataFrame:
        """Convert a list of ZonalPrice records to a DataFrame with a datetime column.

        The ``datetime`` column is derived from ``flow_date`` and ``period``:
        period 1 → 00:00, period 2 → 00:15, …, period 96 → 23:45.
        """
        df = pd.DataFrame([p.model_dump() for p in prices])
        df["datetime"] = df["flow_date"].apply(lambda d: datetime.combine(d, time())) + pd.to_timedelta(
            (df["period"] - 1) * 15, unit="m"
        )
        return df

    def pivot(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pivot the long-format DataFrame from convert_date into wide format.

        Each row represents one period; zone names become price columns.
        Columns are renamed to match the GME published format:
        Data, Mercato, <zones...>, Periodo, Granularity, Datetime.
        """
        wide = df.pivot_table(
            index=["flow_date", "market", "period", "datetime"],
            columns="zone",
            values="price_eur_mwh",
            aggfunc="first",
        ).reset_index()

        wide.columns.name = None
        wide = wide.rename(
            columns={
                "flow_date": "Data",
                "market": "Mercato",
                "period": "Periodo",
                "datetime": "Datetime",
            }
        )
        wide["Granularity"] = self._granularity

        zone_cols = [c for c in wide.columns if c not in ("Data", "Mercato", "Periodo", "Granularity", "Datetime")]
        return wide[["Data", "Mercato"] + zone_cols + ["Periodo", "Granularity", "Datetime"]]

    def _authenticate(self) -> str:
        response = self._post_json(
            f"{self._base_url}/{self._endpoint}/Auth",
            {"Login": self._username, "Password": self._password},
        )
        success = response.get("success")
        token = response.get("token")
        reason = response.get("reason")

        if not success or not token:
            msg = str(reason or "GME authentication failed.")
            logger.error("Authentication failed", reason=msg)
            raise GMEError(msg)

        return str(token)

    def _request_records(
        self,
        token: str,
        interval_start: date,
        interval_end: date,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "Platform": self._platform,
            "Segment": self._segment,
            "DataName": self._data_name,
            "IntervalStart": interval_start.strftime("%Y%m%d"),
            "IntervalEnd": interval_end.strftime("%Y%m%d"),
            "Attributes": {"GranularityType": self._granularity},
        }
        response = self._post_json(
            f"{self._base_url}/{self._endpoint}/RequestData",
            payload,
            headers={"Authorization": f"Bearer {token}"},
        )

        content = response.get("contentResponse")
        result = response.get("resultRequest")
        fmt = response.get("formatType")

        if not content:
            msg = str(result or "GME data request failed.")
            logger.error("Data request failed", reason=msg)
            raise GMEError(msg)

        return self._decode_and_extract(str(content), str(fmt) if fmt else None)

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged_headers: dict[str, str] = {"Content-Type": "application/json"}
        if headers:
            merged_headers.update(headers)

        try:
            response = httpx.post(
                url,
                json=payload,
                headers=merged_headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.RequestError as exc:
            raise GMEError(f"Connection to GME API failed: {exc}") from exc

    def _decode_and_extract(self, content_response: str, format_type: str | None) -> list[dict[str, Any]]:
        """Base64-decode the API payload, unzip if needed, and return the record list."""
        raw = base64.b64decode(content_response)

        if format_type and format_type.endswith(".json"):
            payload: Any = json.loads(raw.decode("utf-8"))
        else:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = [n for n in archive.namelist() if not n.endswith("/")]
                if not names:
                    raise GMEError("GME returned an empty archive.")
                json_name = next((n for n in names if n.lower().endswith(".json")), names[0])
                with archive.open(json_name) as handle:
                    payload = json.load(handle)

        return self._extract_records(payload)

    def _extract_records(self, payload: Any) -> list[dict[str, Any]]:
        """Normalise the JSON payload to a flat list of record dicts."""
        if isinstance(payload, list):
            records: list[Any] = payload
        else:
            raise GMEError("GME response is not valid JSON.")

        if not all(isinstance(r, dict) for r in records):
            raise GMEError("GME records do not have the expected format.")
        return records  # type: ignore[return-value]
