from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock

from py_der_61850.clients.alfa_sinapsi_client import AlfaSinapsiClient


class AlfaSinapsiClientReadTests(unittest.TestCase):
    def _build_client(self) -> AlfaSinapsiClient:
        client = AlfaSinapsiClient.__new__(AlfaSinapsiClient)
        client.get_last_value = MagicMock()
        return client

    def test_read_applies_negative_multiplier_to_numeric_value(self) -> None:
        client = self._build_client()
        response = MagicMock()
        response.du = "DU1"
        response.pod = "POD1"
        response.timestamp = datetime(2026, 4, 21, tzinfo=timezone.utc)
        response.value = MagicMock(return_value=1234)
        client.get_last_value.return_value = response

        value = AlfaSinapsiClient.read(
            client,
            pod="IT001E00000001",
            obis="1-0:1.8.0.255_3,0_2",
            unit="Wh",
            activation_key="activation-key",
            multiplier=-1,
        )

        self.assertEqual(value, -1234)
        client.get_last_value.assert_called_once_with(
            activation_key="activation-key",
            pod="IT001E00000001",
            obis="1-0:1.8.0.255_3,0_2",
        )
        response.value.assert_called_once_with("1-0:1.8.0.255_3,0_2")

    def test_read_keeps_numeric_value_when_multiplier_is_one(self) -> None:
        client = self._build_client()
        response = MagicMock()
        response.du = "DU2"
        response.pod = "POD2"
        response.timestamp = datetime(2026, 4, 21, tzinfo=timezone.utc)
        response.value = MagicMock(return_value=987)
        client.get_last_value.return_value = response

        value = AlfaSinapsiClient.read(
            client,
            pod="IT001E00000002",
            obis="1-0:1.8.0.255_3,0_2",
            unit="Wh",
            activation_key="activation-key",
            multiplier=1,
        )

        self.assertEqual(value, 987)
        client.get_last_value.assert_called_once_with(
            activation_key="activation-key",
            pod="IT001E00000002",
            obis="1-0:1.8.0.255_3,0_2",
        )
        response.value.assert_called_once_with("1-0:1.8.0.255_3,0_2")

    def test_read_keeps_non_numeric_value_unchanged(self) -> None:
        client = self._build_client()
        response = MagicMock()
        response.du = "DU3"
        response.pod = "POD3"
        response.timestamp = datetime(2026, 4, 21, tzinfo=timezone.utc)
        response.value = MagicMock(return_value="unavailable")
        client.get_last_value.return_value = response

        value = AlfaSinapsiClient.read(
            client,
            pod="IT001E00000000",
            obis="1-0:1.8.0.255_3,0_2",
            unit="Wh",
            activation_key="activation-key",
            multiplier=-1,
        )

        self.assertEqual(value, "unavailable")
        client.get_last_value.assert_called_once_with(
            activation_key="activation-key",
            pod="IT001E00000000",
            obis="1-0:1.8.0.255_3,0_2",
        )
        response.value.assert_called_once_with("1-0:1.8.0.255_3,0_2")
