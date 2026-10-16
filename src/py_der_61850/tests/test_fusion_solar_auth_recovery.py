import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from py_der_61850.clients.fusion_solar_client import (
    DeviceKpiPayload,
    FusionSolarAuthError,
    FusionSolarClient,
    LoginPayload,
)


class FusionSolarClientAuthRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _build_client(self) -> FusionSolarClient:
        client = FusionSolarClient.__new__(FusionSolarClient)
        client.username = "user"
        client.password = "pass"
        client.refresh_token = "refresh-token"
        client.base_url = "https://example.com"
        client.oauth_base_url = "https://oauth.example.com"
        client.default_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        client.token_cache_path = Path(self._tmpdir.name) / "fusion_solar_token.json"
        client.client = MagicMock()
        client.client.cookies = httpx.Cookies()
        client._rate_limit_window_seconds = 14 * 60
        client._rate_limit_max_calls = 5
        client._call_history = {}
        client.debug = False
        client.plant_device_data = {}
        client.plant_code = "PLANT"
        return client

    @staticmethod
    def _response(
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        json_body: dict | list | None = None,
        cookie_token: str | None = None,
    ) -> MagicMock:
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        response.headers = headers or {}
        response.cookies = httpx.Cookies()
        if cookie_token is not None:
            response.cookies.set("XSRF-TOKEN", cookie_token)
        response.raise_for_status = MagicMock()
        response.json.return_value = {} if json_body is None else json_body
        return response

    def test_get_xsrf_token_uses_cookie_fallback(self) -> None:
        client = self._build_client()
        client.client.post.return_value = self._response(
            json_body={"success": True, "failCode": 0},
            cookie_token="cookie-token",
        )

        token = client.get_xsrf_token(LoginPayload(userName="user", systemCode="pass"))

        self.assertEqual(token, "cookie-token")

    def test_get_xsrf_token_raises_when_token_missing_everywhere(self) -> None:
        client = self._build_client()
        client.client.post.side_effect = [
            self._response(json_body={"success": True, "failCode": 0}),
            self._response(json_body={"success": True, "failCode": 0}),
        ]

        with self.assertRaises(FusionSolarAuthError):
            client.get_xsrf_token(LoginPayload(userName="user", systemCode="pass"))

        self.assertEqual(client.client.post.call_count, 2)

    def test_get_device_kpi_retries_after_auth_failure_payload(self) -> None:
        client = self._build_client()
        client.client.post.side_effect = [
            self._response(headers={"xsrf-token": "token-1"}, json_body={"success": True, "failCode": 0}),
            self._response(
                json_body={"success": False, "failCode": 305, "message": "INVALID_CREDENTIAL"},
            ),
            self._response(headers={"xsrf-token": "token-2"}, json_body={"success": True, "failCode": 0}),
            self._response(
                json_body={
                    "data": [
                        {
                            "devId": 1,
                            "sn": "SN1",
                            "dataItemMap": {"battery_soc": 55.0},
                        }
                    ]
                }
            ),
        ]

        result = client.get_device_kpi(None, DeviceKpiPayload(devIds="1", devTypeId=39))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].devId, 1)
        first_kpi_call = client.client.post.call_args_list[1].kwargs["headers"]["XSRF-TOKEN"]
        second_kpi_call = client.client.post.call_args_list[3].kwargs["headers"]["XSRF-TOKEN"]
        self.assertEqual(first_kpi_call, "token-1")
        self.assertEqual(second_kpi_call, "token-2")

    def test_get_device_kpi_never_sends_none_xsrf_header(self) -> None:
        client = self._build_client()
        client.client.post.side_effect = [
            self._response(json_body={"success": True, "failCode": 0}, cookie_token="cookie-token"),
            self._response(
                json_body={
                    "data": [
                        {
                            "devId": 1,
                            "sn": "SN1",
                            "dataItemMap": {"battery_soc": 55.0},
                        }
                    ]
                }
            ),
        ]

        client.get_device_kpi(None, DeviceKpiPayload(devIds="1", devTypeId=39))

        headers = client.client.post.call_args_list[1].kwargs["headers"]
        self.assertEqual(headers["XSRF-TOKEN"], "cookie-token")
        self.assertIsNotNone(headers["XSRF-TOKEN"])


if __name__ == "__main__":
    unittest.main()
