from datetime import datetime, timezone
import unittest

from py_der_61850.clients.influxdb_client import InfluxClient


class _FakeQueryApi:
    def __init__(self) -> None:
        self.query_text: str | None = None
        self.org: str | None = None

    def query(self, *, query: str, org: str):
        self.query_text = query
        self.org = org
        return []


class _FakeInfluxDBClient:
    def __init__(self, query_api: _FakeQueryApi) -> None:
        self._query_api = query_api

    def query_api(self) -> _FakeQueryApi:
        return self._query_api


class TestInfluxClient(unittest.TestCase):
    def test_get_last_groups_quality_series_before_sorting_and_limiting(self) -> None:
        query_api = _FakeQueryApi()
        client = InfluxClient.__new__(InfluxClient)
        client.client = _FakeInfluxDBClient(query_api)
        client.org = "org"

        result = InfluxClient.get_last(
            client,
            bucket="mise",
            measurement="PODXX2",
            field="PODXX2_bess_MMTN1.DmdWh.actVal",
            tag_id="PODXX2_bess_MMTN1.DmdWh.actVal",
            quality="good",
            at_or_before=datetime(2026, 5, 4, 4, 29, 31, tzinfo=timezone.utc),
        )

        self.assertIsNone(result)
        query = query_api.query_text or ""
        self.assertIn('exists r.quality and r.quality == "good"', query)
        self.assertIn('r["_time"] <= time(v: "2026-05-04T04:29:31Z")', query)
        self.assertLess(query.index("group(columns: [])"), query.index('sort(columns: ["_time"], desc: true)'))
        self.assertLess(query.index('sort(columns: ["_time"], desc: true)'), query.index("limit(n: 1)"))


if __name__ == "__main__":
    unittest.main()
