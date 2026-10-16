from datetime import datetime, timezone

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from loguru import logger


class InfluxClient:
    def __init__(self, url: str, token: str, org: str):
        self.url = url
        self.token = token
        self.org = org

        self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def get(
        self,
        bucket: str,
        measurement: str,
        fields: list[str] | None = None,
        tags: dict[str, str] | None = None,
        start: str = "-1h",
        stop: str = "now()",
        limit: int | None = None,
        extras: list[str] | None = None,
    ) -> list[dict]:
        query_api = self.client.query_api()

        query = f'from(bucket: "{bucket}") |> range(start: {start}, stop: {stop}) |> filter(fn: (r) => r["_measurement"] == "{measurement}")'

        if fields:
            field_filters = " or ".join([f'r["_field"] == "{f}"' for f in fields])
            query += f" |> filter(fn: (r) => {field_filters})"

        if tags:
            for k, v in tags.items():
                query += f' |> filter(fn: (r) => r["{k}"] == "{v}")'

        if limit:
            query += f" |> limit(n: {limit})"

        if extras:
            for extra in extras:
                query += f" |> {extra}"

        logger.debug(f"InfluxDB query: {query}")
        tables = query_api.query(query=query, org=self.org)

        results = []
        for table in tables:
            for record in table.records:
                results.append(
                    {
                        "Datetime": record.get_time(),
                        "measurement": record.get_measurement(),
                        "field": record.get_field(),
                        "value": record.get_value(),
                        **record.values,
                    }
                )

        return results

    def write(
        self,
        data: list[dict],
        bucket: str,
        measurement: str,
        tags: list[str],
        fields: list[str],
        time_field: str | None = None,
    ):
        for doc in data:
            point = Point(measurement)

            for tag in tags:
                if tag in doc:
                    point = point.tag(tag, str(doc[tag]))

            for field in fields:
                if field in doc:
                    point = point.field(doc[field], doc["value"])

            if time_field and time_field in doc:
                point = point.time(doc[time_field], WritePrecision.NS)

            self.write_api.write(bucket=bucket, org=self.org, record=point)

    def get_last(
        self,
        bucket: str,
        measurement: str,
        field: str,
        tag_id: str | None = None,
        start: str = "-365d",
        stop: str = "now()",
        quality: str | None = None,
        at_or_before: datetime | None = None,
    ) -> dict | None:
        extras = []
        if quality is not None:
            extras.append(f'filter(fn: (r) => exists r.quality and r.quality == "{quality}")')
        if at_or_before is not None:
            extras.append(f'filter(fn: (r) => r["_time"] <= time(v: "{_format_flux_time(at_or_before)}"))')
        extras.extend(
            [
                "group(columns: [])",
                'sort(columns: ["_time"], desc: true)',
                "limit(n: 1)",
            ]
        )
        results = self.get(
            bucket=bucket,
            measurement=measurement,
            fields=[field],
            tags={"id": tag_id or field},
            start=start,
            stop=stop,
            extras=extras,
        )
        return results[0] if results else None


def _format_flux_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
