import unittest
from unittest.mock import MagicMock

from py_der_61850.clients.fusion_solar_client import DeviceData, FusionSolarClient

# Device list anonimizzata di una stazione residenziale (NE=900000001), con la stessa
# forma restituita da getDevList. I devId sono quelli usati dai mapping huawei nel
# config utente; il devTypeId serve a read() per get_device_kpi.
SAMPLE_DEVICES = [
    {
        "id": 1000000900000003,
        "devDn": "NE=900000003",
        "devName": "INV-0000X0000001",
        "devTypeId": 38,  # inverter residenziale
        "stationCode": "NE=900000001",
        "latitude": 0.0,
        "longitude": 0.0,
        "esnCode": "0000X0000001",
    },
    {
        "id": 1000000900000005,
        "devDn": "NE=900000005",
        "devName": "Battery-1",
        "devTypeId": 39,  # batteria
        "stationCode": "NE=900000001",
        "latitude": 0.0,
        "longitude": 0.0,
    },
    {
        "id": 1000000900000007,
        "devDn": "NE=900000007",
        "devName": "Meter-1",
        "devTypeId": 47,  # contatore
        "stationCode": "NE=900000001",
        "latitude": 0.0,
        "longitude": 0.0,
    },
]


class DeviceFallbackTests(unittest.TestCase):
    def _client(self, fallback: list[dict]) -> FusionSolarClient:
        client = FusionSolarClient.__new__(FusionSolarClient)
        client._device_fallback = fallback
        client.username = "user"
        client.password = "pass"
        client.plant_code = "NE=900000001"
        client.plant_device_data = {}
        client._rate_limit_window_seconds = 14 * 60
        return client

    def test_fallback_used_when_getdevlist_fails_20056(self) -> None:
        # getDevList lancia (simula failCode=20056 lato Huawei sulla stazione).
        client = self._client(SAMPLE_DEVICES)
        client.get_devices = MagicMock(side_effect=RuntimeError("getDevList failCode=20056"))

        devices = client._get_devices_with_fallback("xsrf-token", "NE=900000001")

        # Deve usare il fallback invece di propagare l'errore.
        self.assertEqual(len(devices), 3)
        self.assertTrue(all(isinstance(d, DeviceData) for d in devices))
        # I devId del config devono esserci, col devTypeId giusto (read() ne ha bisogno).
        by_id = {d.id: d for d in devices}
        self.assertEqual(by_id[1000000900000005].devTypeId, 39)  # batteria
        self.assertEqual(by_id[1000000900000003].devTypeId, 38)  # inverter
        self.assertEqual(by_id[1000000900000007].devTypeId, 47)  # contatore

    def test_live_result_used_when_getdevlist_ok(self) -> None:
        # Quando getDevList funziona, si usa il risultato vivo e si IGNORA il fallback.
        client = self._client(SAMPLE_DEVICES)
        live = [DeviceData.model_validate(SAMPLE_DEVICES[0])]
        client.get_devices = MagicMock(return_value=live)

        devices = client._get_devices_with_fallback("xsrf-token", "NE=900000001")

        self.assertEqual(devices, live)
        client.get_devices.assert_called_once()

    def test_raises_when_no_fallback_configured(self) -> None:
        # Senza fallback, l'errore originale deve propagare (nessun mascheramento silenzioso).
        client = self._client([])
        client.get_devices = MagicMock(side_effect=RuntimeError("getDevList failCode=20056"))

        with self.assertRaises(RuntimeError):
            client._get_devices_with_fallback("xsrf-token", "NE=900000001")

    def test_read_finds_device_after_fallback(self) -> None:
        # End-to-end: dopo il fallback, read() trova il device per devId e chiama
        # get_device_kpi col devTypeId corretto, restituendo il valore letto.
        client = self._client(SAMPLE_DEVICES)
        client.get_devices = MagicMock(side_effect=RuntimeError("getDevList failCode=20056"))
        client.devices = client._get_devices_with_fallback("xsrf-token", "NE=900000001")

        client.get_xsrf_token = MagicMock(return_value="xsrf-token")

        captured = {}

        def fake_get_device_kpi(xsrf, payload):
            captured["devIds"] = payload.devIds
            captured["devTypeId"] = payload.devTypeId
            kpi = MagicMock()
            kpi.devId = 1000000900000005
            kpi.dataItemMap = {"battery_soc": 55.0}
            return [kpi]

        client.get_device_kpi = fake_get_device_kpi

        value = client.read(
            address="dataItemMap.battery_soc",
            type="int",
            function="get_device_kpi",
            devId=1000000900000005,
            multiplier=1,
        )

        # read() ha usato il devTypeId della batteria (39) ricavato dal fallback.
        self.assertEqual(captured["devTypeId"], 39)
        self.assertEqual(captured["devIds"], "1000000900000005")
        self.assertEqual(value, 55)  # 55.0 * 1 -> int 55


if __name__ == "__main__":
    unittest.main()
