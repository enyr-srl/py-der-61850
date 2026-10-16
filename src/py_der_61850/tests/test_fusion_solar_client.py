import os
import tempfile
import unittest

import pytest

from py_der_61850.clients.fusion_solar_client import (
    DeviceKpiPayload,
    DevicePayload,
    FusionSolarClient,
    LoginPayload,
    RequestPayload,
    StationKpiPayload,
)

# Calls the real FusionSolar API: excluded by default, run explicitly with `-m integration`.
pytestmark = pytest.mark.integration


class FusionSolarClientTests(unittest.TestCase):
    client: FusionSolarClient
    xsrf_token: str
    base_url: str
    oauth_base_url: str
    username: str
    password: str
    refresh_token: str
    plant_code: str
    _tmpdir: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        required = [
            "FUSION_SOLAR_USERNAME",
            "FUSION_SOLAR_PASSWORD",
            "FUSION_SOLAR_REFRESH_TOKEN",
            "FUSION_SOLAR_OAUTH_BASE_URL",
            "FUSION_SOLAR_PLANT_CODE",
        ]
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise unittest.SkipTest(f"Missing env vars: {', '.join(missing)}")

        cls.base_url = os.getenv("FUSION_SOLAR_BASE_URL", "https://eu5.fusionsolar.huawei.com")
        cls.oauth_base_url = os.getenv("FUSION_SOLAR_OAUTH_BASE_URL", "")
        cls.username = os.getenv("FUSION_SOLAR_USERNAME", "")
        cls.password = os.getenv("FUSION_SOLAR_PASSWORD", "")
        cls.refresh_token = os.getenv("FUSION_SOLAR_REFRESH_TOKEN", "")
        cls.plant_code = os.getenv("FUSION_SOLAR_PLANT_CODE", "")

        cls._tmpdir = tempfile.TemporaryDirectory()
        token_path = f"{cls._tmpdir.name}/fusion_solar_token.json"
        cls.client = FusionSolarClient(
            base_url=cls.base_url,
            oauth_base_url=cls.oauth_base_url,
            token_cache_path=token_path,
        )
        payload = LoginPayload(userName=cls.username, systemCode=cls.password)
        cls.xsrf_token = cls.client.get_xsrf_token(payload=payload)
        if not cls.xsrf_token:
            raise unittest.SkipTest("Unable to obtain XSRF token.")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_get_stations_devices_kpi(self) -> None:
        stations = self.client.get_stations(access_token=self.xsrf_token, payload=RequestPayload(pageNo=1))
        self.assertTrue(stations)

    def test_get_devices(self) -> None:
        plant_code = self.plant_code
        devices = self.client.get_devices(
            access_token=self.xsrf_token,
            payload=DevicePayload(stationCodes=plant_code),
        )
        self.assertIsInstance(devices, list)
        if devices:
            self.assertEqual(devices[0].stationCode, plant_code)

    def test_get_station_kpi(self) -> None:
        plant_code = self.plant_code
        kpi = self.client.get_station_kpi(
            access_token=self.xsrf_token,
            payload=StationKpiPayload(stationCodes=plant_code),
        )
        self.assertIsNotNone(kpi)
        self.assertTrue(hasattr(kpi, "real_health_state"))

    def test_get_all_data(self) -> None:
        stations = self.client.get_stations(access_token=self.xsrf_token, payload=RequestPayload(pageNo=1))
        devices = self.client.get_devices(
            access_token=self.xsrf_token,
            payload=DevicePayload(stationCodes=self.plant_code),
        )
        station_kpi = self.client.get_station_kpi(
            access_token=self.xsrf_token,
            payload=StationKpiPayload(stationCodes=self.plant_code),
        )
        for device in devices:
            if device.devTypeId == 39:
                device_kpi = self.client.get_device_kpi(
                    access_token=self.xsrf_token,
                    payload=DeviceKpiPayload(devIds=str(device.id), devTypeId=39),
                )
                self.assertIsNotNone(device_kpi)
        self.assertIsNotNone(stations)
        self.assertIsNotNone(station_kpi)

    def test_refresh_access_token(self) -> None:
        access_token = self.client.refresh_access_token(refresh_token=self.refresh_token)
        self.assertTrue(access_token)


if __name__ == "__main__":
    unittest.main()
