import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import httpx

from py_der_61850.clients.fusion_solar_client import (
    HUAWEI_WRITE_FAILED,
    HUAWEI_WRITE_QUEUED,
    HUAWEI_WRITE_SENT,
    FusionSolarClient,
    _PendingChargeDischargeCommand,
)


class FusionSolarClientZeroWriteTests(unittest.TestCase):
    def _build_client(self) -> FusionSolarClient:
        client = FusionSolarClient.__new__(FusionSolarClient)
        client.refresh_token = "refresh-token"
        client.base_url = "https://example.com"
        client.plant_code = "PLANT"
        client.client = MagicMock()
        client.refresh_access_token = MagicMock(return_value="access-token")

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "success": True,
            "failCode": 0,
            "data": {
                "requestID": 1,
                "result": [{"dispatchResult": 0, "subTaskId": "sub-task"}],
            },
        }
        client.client.post.return_value = response
        return client

    def test_zero_value_is_mapped_to_one_watt_charge(self) -> None:
        client = self._build_client()

        result = FusionSolarClient.write(client, "0.0", control_type=2)

        payload = client.client.post.call_args.kwargs["json"]["tasks"][0]
        self.assertEqual(result, HUAWEI_WRITE_SENT)
        self.assertEqual(payload["dispatchSwitch"], 1)
        self.assertEqual(payload["powerDispatch"], 1)
        last_task = client._charge_discharge_last_task
        self.assertEqual(
            last_task["busy_until"] - last_task["accepted_at"],
            timedelta(minutes=last_task["dispatchTime"], seconds=30),
        )

    def test_command_is_queued_when_previous_task_is_estimated_busy(self) -> None:
        client = self._build_client()
        client._charge_discharge_busy_until = datetime.now() + timedelta(minutes=1)
        client._schedule_charge_discharge_retry_locked = MagicMock()

        result = FusionSolarClient.write(client, "1000.0", control_type=2)

        self.assertEqual(result, HUAWEI_WRITE_QUEUED)
        client.client.post.assert_not_called()
        self.assertEqual(client._charge_discharge_pending_command.value, "1000.0")
        client._schedule_charge_discharge_retry_locked.assert_called_once()

    def test_duplicate_response_keeps_command_pending_for_retry(self) -> None:
        client = self._build_client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "success": False,
            "failCode": 2,
            "message": "Failed to deliver the battery charge/discharge task.",
            "data": {
                "requestID": None,
                "result": [
                    {
                        "dispatchResult": 1,
                        "subTaskId": None,
                        "description": "The duplicate task is running, battery DN: NE=900000107",
                    }
                ],
            },
        }
        client.client.post.return_value = response
        client._schedule_charge_discharge_retry_locked = MagicMock()

        result = FusionSolarClient.write(client, "1000.0", control_type=2)

        self.assertEqual(result, HUAWEI_WRITE_QUEUED)
        self.assertEqual(client._charge_discharge_pending_command.value, "1000.0")
        self.assertTrue(client._charge_discharge_pending_command.duplicate_retry_attempted)
        client._schedule_charge_discharge_retry_locked.assert_called_once_with(
            delay_seconds=10,
            reason="huawei_duplicate_task_running",
        )

    def test_duplicate_response_after_single_retry_drops_command(self) -> None:
        client = self._build_client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "success": False,
            "failCode": 2,
            "message": "Failed to deliver the battery charge/discharge task.",
            "data": {
                "requestID": None,
                "result": [
                    {
                        "dispatchResult": 1,
                        "subTaskId": None,
                        "description": "The duplicate task is running, battery DN: NE=900000107",
                    }
                ],
            },
        }
        client.client.post.return_value = response
        client._schedule_charge_discharge_retry_locked = MagicMock()

        result = FusionSolarClient.write(
            client,
            "1000.0",
            control_type=2,
            _from_queue=True,
            _duplicate_retry_attempted=True,
        )

        self.assertEqual(result, HUAWEI_WRITE_FAILED)
        self.assertIsNone(client._charge_discharge_pending_command)
        client._schedule_charge_discharge_retry_locked.assert_not_called()

    def test_dispatch_time_tracks_remaining_minutes_after_quarter_window(self) -> None:
        self.assertIsNone(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 14, 29)))
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 14, 30)), 15)
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 15, 0)), 15)
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 15, 30)), 15)
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 15, 31)), 14)
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 16, 30)), 13)
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 17, 30)), 12)
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 25, 10)), 4)
        self.assertIsNone(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 29, 10)))
        self.assertEqual(FusionSolarClient._dispatch_time_for_now(datetime(2026, 4, 23, 7, 29, 30)), 15)

    def test_flush_pending_command_drops_after_timeout(self) -> None:
        client = self._build_client()
        FusionSolarClient._ensure_charge_discharge_queue_state(client)
        client.write = MagicMock(side_effect=httpx.ReadTimeout("timed out"))
        client._schedule_charge_discharge_retry_locked = MagicMock()

        with client._charge_discharge_lock:
            FusionSolarClient._queue_charge_discharge_command_locked(
                client,
                _PendingChargeDischargeCommand(
                    value="1000.0",
                    control_type=2,
                    command_timestamp=datetime(2026, 4, 24, 8, 59, 36),
                ),
                reason="test",
            )

        FusionSolarClient._flush_pending_charge_discharge_command(client)

        self.assertIsNone(client._charge_discharge_pending_command)
        client._schedule_charge_discharge_retry_locked.assert_not_called()

    def test_newer_pending_command_replaces_older_one(self) -> None:
        client = self._build_client()
        FusionSolarClient._ensure_charge_discharge_queue_state(client)
        older = datetime(2026, 4, 24, 8, 29, 42)
        newer = older + timedelta(minutes=15)

        with client._charge_discharge_lock:
            FusionSolarClient._queue_charge_discharge_command_locked(
                client,
                _PendingChargeDischargeCommand(
                    value="1000.0",
                    control_type=2,
                    command_timestamp=older,
                ),
                reason="older",
            )
            FusionSolarClient._queue_charge_discharge_command_locked(
                client,
                _PendingChargeDischargeCommand(
                    value="2500.0",
                    control_type=2,
                    command_timestamp=newer,
                ),
                reason="newer",
            )

        self.assertEqual(client._charge_discharge_pending_command.value, "2500.0")
        self.assertEqual(client._charge_discharge_pending_command.command_timestamp, newer)

    def test_write_does_not_retry_after_auth_failure_payload(self) -> None:
        client = self._build_client()
        auth_failure = MagicMock()
        auth_failure.status_code = 200
        auth_failure.raise_for_status = MagicMock()
        auth_failure.json.return_value = {
            "failCode": 305,
            "success": False,
            "message": "INVALID_CREDENTIAL",
        }
        client.client.post.return_value = auth_failure
        client.refresh_access_token = MagicMock(return_value="access-token-1")

        result = FusionSolarClient.write(client, "1000.0", control_type=2)

        self.assertEqual(result, HUAWEI_WRITE_FAILED)
        self.assertEqual(client.client.post.call_count, 1)
        self.assertEqual(client.refresh_access_token.call_count, 1)

    def test_write_drops_command_after_persistent_auth_failure(self) -> None:
        client = self._build_client()
        auth_failure = MagicMock()
        auth_failure.status_code = 200
        auth_failure.raise_for_status = MagicMock()
        auth_failure.json.return_value = {
            "failCode": 305,
            "success": False,
            "message": "INVALID_CREDENTIAL",
        }
        client.client.post.return_value = auth_failure
        client.refresh_access_token = MagicMock(return_value="access-token-1")
        client._schedule_charge_discharge_retry_locked = MagicMock()

        result = FusionSolarClient.write(client, "1000.0", control_type=2)

        self.assertEqual(result, HUAWEI_WRITE_FAILED)
        self.assertIsNone(client._charge_discharge_pending_command)
        client._schedule_charge_discharge_retry_locked.assert_not_called()

    def test_refresh_http_error_does_not_escape_write(self) -> None:
        client = self._build_client()
        response = httpx.Response(502, request=httpx.Request("POST", "https://example.com/refresh"))
        client.refresh_access_token = MagicMock(
            side_effect=httpx.HTTPStatusError("bad gateway", request=response.request, response=response)
        )
        client._schedule_charge_discharge_retry_locked = MagicMock()

        result = FusionSolarClient.write(client, "1000.0", control_type=2)

        self.assertEqual(result, HUAWEI_WRITE_FAILED)
        self.assertIsNone(client._charge_discharge_pending_command)
        client._schedule_charge_discharge_retry_locked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
